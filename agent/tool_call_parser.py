# agent/tool_call_parser.py
#
# WHY THIS FILE EXISTS
# ────────────────────
# LLaMA-3.3-70b is not stable when it formats tool calls in its text output.
# Sometimes it returns JSON, sometimes XML, sometimes a plain English sentence.
# Rather than trying to "fix" LLaMA, this file takes a different approach:
#
#   We already know every tool's name and every parameter it needs.
#   So we scan the raw string for what we know, and ignore the formatting noise.
#
# The two-step strategy:
#   Step 1 → find the tool name  (scan for known names as substrings)
#   Step 2 → find each argument  (regex for "param_name" followed by its value)

import re
import json
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# TOOL REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
#
# This is the single source of truth for what tools exist and what they need.
# Each entry maps:
#   tool_name → list of (parameter_name, default_value)
#
# The default_value is used when LLaMA forgets to include a parameter.
# None means "required — no sensible default exists".

TOOL_REGISTRY: dict[str, list[tuple[str, object]]] = {
    "fetch_logs": [
        ("service",  None),   # required — which service to fetch logs for
        ("severity", "ERROR"), # optional — default to ERROR if not mentioned
        ("limit",    20),      # optional — default to 20 log lines
    ],
    "check_metrics": [
        ("service",  None),   # required
    ],
    "search_past_incidents": [
        ("query",    None),   # required — the search query string
    ],
    "generate_report": [
        ("ticket_id",          None),    # required
        ("service",            None),    # required
        ("priority",           None),    # required
        ("category",           None),    # required
        ("root_cause",         None),    # required
        ("confidence",         None),    # required
        ("resolution_summary", None),    # required
        ("evidence_summary",   None),    # required
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — FIND THE TOOL NAME
# ─────────────────────────────────────────────────────────────────────────────

def _extract_tool_name(raw: str) -> Optional[str]:
    """
    Scans the raw LLaMA string for any known tool name.

    We simply check whether each known tool name appears anywhere
    in the string as a substring. This works regardless of whether
    the name is inside JSON quotes, XML tags, or plain text because
    the name itself ("fetch_logs", "check_metrics", etc.) is always
    a distinctive enough string that it won't appear accidentally.

    Returns the first matching tool name, or None if nothing matched.

    Example inputs that all return "fetch_logs":
      '{"name": "fetch_logs", "service": "auth"}'
      '<tool_name>fetch_logs</tool_name>'
      'I will call fetch_logs with service=auth'
    """
    for tool_name in TOOL_REGISTRY:
        # tool_name is something like "fetch_logs"
        # We check if that exact string appears anywhere in raw
        if tool_name in raw:
            return tool_name

    # Nothing matched — LLaMA didn't produce a recognisable tool call
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — FIND EACH PARAMETER VALUE
# ─────────────────────────────────────────────────────────────────────────────

def _extract_param_value(param_name: str, raw: str) -> Optional[str]:
    r"""
    Given a parameter name and the raw LLaMA string, pulls out the value
    for that parameter using a regex designed to handle all three formats:

      JSON:  "service": "auth-service"   -> captures: auth-service
      XML:   <service>auth-service</service> -> captures: auth-service
      Text:  service=auth-service        -> captures: auth-service
      Text:  service: auth-service       -> captures: auth-service

    HOW THE REGEX WORKS (explained piece by piece):
    -----------------------------------------------
    The regex has two alternative patterns joined by  |

    Pattern A -- JSON / key-value style:
      param_name        literal parameter name e.g. "service"
      \s*               zero or more spaces
      [":=]             one of  "  :  =  (the separator between name and value)
      \s*               zero or more spaces
      "?                optional opening quote
      ([^",:}\]<\n]+)   CAPTURE GROUP -- the value itself:
                          [^  ...]  means "any character EXCEPT these"
                          "  closing quote
                          ,  JSON comma (value ended)
                          :  another colon (we've gone too far)
                          }  JSON closing brace
                          ]  JSON closing bracket
                          <  XML tag opening (value ended)
                          \n newline (value ended)
                          +  one or more such characters
      "?                optional closing quote

    Pattern B -- XML tag style:
      <param_name>      literal opening tag  e.g. <service>
      ([^<]+)           CAPTURE GROUP -- everything up to the closing <
      </param_name>     literal closing tag  e.g. </service>

    We use re.IGNORECASE so "Service" or "SERVICE" also matches.
    We use re.DOTALL so dots match newlines inside multi-line values.
    """

    # Build the two-part regex dynamically using the parameter name
    #
    # Pattern A — JSON style:  "service": "auth-service"
    #   "?param_name"?   the key, optionally surrounded by quotes
    #   \s*[:]\s*        a colon separator with optional spaces
    #   "([^"]+)"        the value in double quotes  ← captures only the quoted part
    #
    # Pattern B — key=value text style:  service=auth-service
    #   param_name       the key with no quotes
    #   \s*=\s*          an equals sign with optional spaces
    #   "?([^",:}\]\n< ]+)"?   value — stops at quote, comma, brace, newline, or space
    #
    # Pattern C — XML tag style:  <service>auth-service</service>
    #   <param_name>     opening tag
    #   ([^<]+)          everything up to the next <
    #   </param_name>    closing tag
    pattern = (
        # Pattern A: JSON  "key": "value"
        rf'"?{param_name}"?\s*:\s*"([^"]+)"'
        r'|'
        # Pattern B: key=value (plain text)
        rf'{param_name}\s*=\s*"?([^",:}}\]\n< ]+)"?'
        r'|'
        # Pattern C: XML <key>value</key>
        rf'<{param_name}>([^<]+)</{param_name}>'
    )

    match = re.search(pattern, raw, re.IGNORECASE | re.DOTALL)

    if not match:
        # Parameter not found anywhere in the string
        return None

    # re.search returns the first match.
    # match.group(1) is Pattern A's capture group  (JSON quoted)
    # match.group(2) is Pattern B's capture group  (key=value text)
    # match.group(3) is Pattern C's capture group  (XML tag)
    # Exactly one of them will be non-None — we return whichever has the value.
    value = match.group(1) or match.group(2) or match.group(3)

    # Clean up: strip surrounding whitespace and any stray quotes
    return value.strip().strip('"').strip("'")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def parse_tool_call(raw: str) -> Optional[dict]:
    """
    Takes the raw LLaMA response string and returns a clean dict:

        {
            "tool_name": "fetch_logs",
            "tool_args": {
                "service":  "auth-service",
                "severity": "ERROR",
                "limit":    20
            }
        }

    Returns None if no recognisable tool name is found in the string.

    HOW TO USE THIS IN investigation_agent.py:
    ───────────────────────────────────────────
    Wherever you currently do:

        tool_name  = tool_call.function.name
        tool_input = json.loads(tool_call.function.arguments)

    You can add a fallback:

        tool_name  = tool_call.function.name
        try:
            tool_input = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            # LLaMA gave us garbage — parse the raw text instead
            parsed = parse_tool_call(tool_call.function.arguments)
            if parsed:
                tool_name  = parsed["tool_name"]
                tool_input = parsed["tool_args"]
            else:
                print("  ⚠️ Could not parse tool call — skipping")
                continue
    """

    # ── Step 1: find the tool name ────────────────────────────────────────────
    tool_name = _extract_tool_name(raw)

    if tool_name is None:
        # The string doesn't mention any known tool — nothing to do
        print(f"  ⚠️ parse_tool_call: no known tool name found in:\n    {raw[:120]}")
        return None

    print(f"  🔍 parse_tool_call: identified tool → '{tool_name}'")

    # ── Step 2a: fast path — try to grab a complete JSON object from the string ─
    #
    # Both new LLaMA formats embed a complete JSON blob for the arguments:
    #
    #   <function=search_past_incidents[]{"query": "auth 500 errors"}</function>
    #   <function=check_metrics={"service": "data-pipeline"}</function>
    #
    # Instead of running per-parameter regexes on these, we pull out the whole
    # { ... } block and parse it in one shot with json.loads().
    # This is more reliable than per-param regexes for tools with many parameters
    # (e.g. generate_report has 8 fields — one json.loads beats 8 regex searches).
    #
    # HOW IT WORKS:
    #   re.search(r'\{.*?\}', raw, re.DOTALL)
    #   \{       literal opening brace
    #   .*?      any characters, as few as possible (non-greedy)
    #            re.DOTALL makes . match newlines too (multi-line JSON bodies)
    #   \}       literal closing brace
    #
    # Non-greedy (.*?) is important: if the string contains two JSON objects,
    # greedy (.*) would eat everything between the first { and the last },
    # while non-greedy stops at the first closing } — giving us the first object.
    #
    # We then try json.loads() on whatever we found. If it succeeds and the
    # result is a dict, we use it directly and skip the per-param loop below.
    json_block_match = re.search(r'\{.*?\}', raw, re.DOTALL)
    if json_block_match:
        try:
            candidate = json.loads(json_block_match.group())
            if isinstance(candidate, dict) and len(candidate) > 0:
                # Successfully parsed a JSON object — use it as tool_args directly.
                # Strip out meta-keys like "name" or "tool" that aren't real params.
                known_params = {p for p, _ in TOOL_REGISTRY[tool_name]}
                tool_args = {k: v for k, v in candidate.items() if k in known_params}
                print(f"  ✅ fast-path JSON extracted: {tool_args}")
                return {"tool_name": tool_name, "tool_args": tool_args}
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON — fall through to the per-param regex approach below
            pass

    # ── Step 2b: per-parameter regex fallback ────────────────────────────────
    # Reaches here only when no valid JSON block was found in the string.
    # Handles plain text, broken JSON, and XML formats.
    tool_args = {}

    # TOOL_REGISTRY[tool_name] is a list like:
    #   [("service", None), ("severity", "ERROR"), ("limit", 20)]
    for param_name, default_value in TOOL_REGISTRY[tool_name]:

        # Try to pull the value out of the raw string
        value = _extract_param_value(param_name, raw)

        if value is not None:
            # Successfully found the value — try to coerce numbers to int
            # so "limit": "20" becomes "limit": 20 (what the tool expects)
            if value.isdigit():
                tool_args[param_name] = int(value)
            else:
                tool_args[param_name] = value

        elif default_value is not None:
            # Parameter missing from LLaMA output — use the registered default
            print(f"    ℹ️  '{param_name}' not found — using default: {default_value!r}")
            tool_args[param_name] = default_value

        else:
            # Required parameter, no default, and LLaMA didn't include it.
            # We still add it as None so execute_tool can handle it gracefully
            # rather than crashing with a KeyError.
            print(f"    ⚠️  required param '{param_name}' missing and has no default")
            tool_args[param_name] = None

    return {
        "tool_name": tool_name,
        "tool_args": tool_args,
    }


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SMOKE TEST  (run:  python tool_call_parser.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    test_cases = [
        # Format 1: clean JSON
        ('{"name": "fetch_logs", "service": "auth-service", "severity": "ERROR", "limit": "50"}',
         "Clean JSON"),

        # Format 2: XML
        ("<tool><name>fetch_logs</name><service>auth-service</service><severity>ERROR</severity></tool>",
         "XML"),

        # Format 3: plain text
        ("I will now call fetch_logs with service=auth-service and severity=ERROR",
         "Plain text key=value"),

        # Format 4: check_metrics
        ('{"tool": "check_metrics", "service": "payment-service"}',
         "check_metrics JSON"),

        # Format 5: search_past_incidents with XML
        ("<tool_call><name>search_past_incidents</name><query>auth 500 errors login failure</query></tool_call>",
         "search_past_incidents XML"),

        # Format 6: generate_report JSON
        ('{"name":"generate_report","ticket_id":"TKT-001","service":"auth","priority":"P1","category":"availability","root_cause":"DB connection pool exhausted","confidence":"high","resolution_summary":"Restart connection pool","evidence_summary":"Logs show timeout errors"}',
         "generate_report JSON"),

        # Format 7: garbage — no tool name
        ("The system seems to be experiencing issues, please wait.",
         "No tool name"),

        # Format 8: <function=name[]{"key":"value"}</function>  — bracket separator
        ('<function=search_past_incidents[]{"query": "auth-service 500 errors and connection pool exhausted"}</function>',
         "<function= with [] separator"),

        # Format 9: <function=name={"key":"value"}</function>  — equals separator
        ('<function=check_metrics={"service":"data-pipeline"}</function>',
         "<function= with = separator"),
    ]

    print("=" * 60)
    print("TOOL CALL PARSER — SMOKE TEST")
    print("=" * 60)

    for raw, label in test_cases:
        print(f"\n[{label}]")
        print(f"  Input: {raw[:80]}{'...' if len(raw) > 80 else ''}")
        result = parse_tool_call(raw)
        if result:
            print(f"  tool_name: {result['tool_name']}")
            print(f"  tool_args: {result['tool_args']}")
        else:
            print("  result: None (no tool found)")