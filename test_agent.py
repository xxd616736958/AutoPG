#!/usr/bin/env python3
"""
End-to-end test cases for db-claude agent using DeepSeek.
Tests the agent's ability to solve real problems with tool use.
"""
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_claude.tools import create_default_tools
from db_claude.agent.query_loop import QueryEngine

# DeepSeek config
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-v4-flash"


def print_section(title: str):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def print_result(result: dict):
    print(f"\n  📊 Summary:")
    print(f"     Type:      {result.get('type')}")
    print(f"     Subtype:   {result.get('subtype')}")
    print(f"     Error:     {result.get('is_error')}")
    print(f"     Duration:  {result.get('duration_ms', 0)}ms")
    print(f"     Turns:     {result.get('num_turns', 0)}")
    print(f"     Stop:      {result.get('stop_reason', 'N/A')}")
    usage = result.get('usage', {})
    if usage:
        print(f"     Tokens in: {usage.get('input_tokens', 0):,}")
        print(f"     Tokens out:{usage.get('output_tokens', 0):,}")

    errors = result.get('errors', [])
    if errors:
        print(f"     Errors:")
        for e in errors:
            print(f"       ❌ {e}")

    text = result.get('result', '')
    if text:
        print(f"\n  📝 Response ({len(text)} chars):")
        print(f"  {'─'*61}")
        display = text[:3000]
        for line in display.split('\n'):
            print(f"  │ {line}")
        if len(text) > 3000:
            print(f"  │ ... [truncated, {len(text) - 3000} more chars]")
        print(f"  {'─'*61}")


async def consume_result(engine: QueryEngine, prompt: str) -> dict:
    """Consume streaming events from submit_message, return final result."""
    final = None
    async for event in engine.submit_message(prompt):
        if event.get("type") == "result":
            final = event
    return final or {"is_error": True, "errors": ["No result received"]}


def create_engine(max_turns: int = 5) -> QueryEngine:
    """Create a QueryEngine configured for DeepSeek."""
    tools = create_default_tools()
    return QueryEngine(
        tools=tools.list_enabled(),
        model_name=DEEPSEEK_MODEL,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        max_turns=max_turns,
        provider="deepseek",
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1",
    )


async def test_case_1_simple_question():
    """Test Case 1: Simple question — no tools needed."""
    print_section("TC1: Simple Question (No Tools)")

    engine = create_engine(max_turns=3)
    result = await consume_result(engine,
        "What is the capital of France? Answer in exactly one sentence."
    )
    print_result(result)

    success = not result.get('is_error') and len(result.get('result', '')) > 0
    print(f"\n  {'✅ PASSED' if success else '❌ FAILED'}")
    return success


async def test_case_2_file_read_and_explain():
    """Test Case 2: Read file + explain."""
    print_section("TC2: File Read + Explain")

    engine = create_engine(max_turns=5)
    result = await consume_result(engine,
        "Read the file 'db_claude/tools/base.py' and explain in 3-4 bullet points "
        "what the Tool base class provides."
    )
    print_result(result)

    success = not result.get('is_error') and len(result.get('result', '')) > 0
    print(f"\n  {'✅ PASSED' if success else '❌ FAILED'}")
    return success


async def test_case_3_bash_and_analysis():
    """Test Case 3: Agent uses Bash + analysis."""
    print_section("TC3: Bash Tool + Analysis")

    engine = create_engine(max_turns=6)
    result = await consume_result(engine,
        "Use bash to list all the Python files in the db_claude/tools/ directory "
        "and show their sizes. Then tell me which is the largest file and what "
        "tool it likely implements."
    )
    print_result(result)

    success = not result.get('is_error') and len(result.get('result', '')) > 0
    print(f"\n  {'✅ PASSED' if success else '❌ FAILED'}")
    return success


async def test_case_4_glob_search():
    """Test Case 4: Glob + Grep search."""
    print_section("TC4: Glob + Grep Search")

    engine = create_engine(max_turns=6)
    result = await consume_result(engine,
        "1. Use Glob to find all __init__.py files in the db_claude/ directory tree.\n"
        "2. Read one of them and tell me what it exports.\n"
        "3. Count how many __init__.py files you found."
    )
    print_result(result)

    success = not result.get('is_error') and len(result.get('result', '')) > 0
    print(f"\n  {'✅ PASSED' if success else '❌ FAILED'}")
    return success


async def test_case_5_code_writing():
    """Test Case 5: Write a file then read it back."""
    print_section("TC5: Write + Read Verification")

    test_file = "/tmp/db_claude_test_demo.py"
    engine = create_engine(max_turns=6)

    result = await consume_result(engine,
        f"Write a Python file to '{test_file}' that contains:\n"
        f"1. A 'factorial(n)' function using recursion\n"
        f"2. A 'main()' function that prints factorial(5)\n"
        f"3. The standard 'if __name__ == \"__main__\"' guard\n"
        f"After writing, read the file back to verify it was created correctly."
    )
    print_result(result)

    file_exists = os.path.exists(test_file)
    print(f"\n  File exists on disk: {'✅ YES' if file_exists else '❌ NO'}")
    if file_exists:
        with open(test_file) as f:
            content = f.read()
        has_fact = 'factorial' in content
        has_main = 'def main' in content or "if __name__" in content
        print(f"  Has factorial(): {'✅ YES' if has_fact else '❌ NO'}")
        print(f"  Has main/guard: {'✅ YES' if has_main else '❌ NO'}")
        print(f"\n  File content:")
        for line in content.split('\n'):
            print(f"    {line}")

    success = not result.get('is_error') and file_exists
    print(f"\n  {'✅ PASSED' if success else '❌ FAILED'}")
    return success


async def main():
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║   db-claude Agent Verification — DeepSeek v4 Flash       ║")
    print(f"║   Model: {DEEPSEEK_MODEL}                                    ║")
    print(f"║   Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                            ║")
    print("╚═══════════════════════════════════════════════════════════╝")

    results = {}

    test_cases = [
        ("tc1_simple", test_case_1_simple_question),
        ("tc2_read_explain", test_case_2_file_read_and_explain),
        ("tc3_bash_analysis", test_case_3_bash_and_analysis),
        ("tc4_glob_search", test_case_4_glob_search),
        ("tc5_code_writing", test_case_5_code_writing),
    ]

    for tc_id, tc_func in test_cases:
        try:
            results[tc_id] = await tc_func()
        except Exception as e:
            import traceback
            print(f"\n  ❌ Exception: {e}")
            traceback.print_exc()
            results[tc_id] = False

    # Summary
    print("\n\n" + "="*65)
    print("  TEST RESULTS SUMMARY")
    print("="*65)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for tc_id, ok in results.items():
        tc_names = {
            "tc1_simple": "Simple Question",
            "tc2_read_explain": "File Read + Explain",
            "tc3_bash_analysis": "Bash + Analysis",
            "tc4_glob_search": "Glob + Grep Search",
            "tc5_code_writing": "Write + Read Verify",
        }
        print(f"  {'✅' if ok else '❌'} {tc_id}: {tc_names.get(tc_id, tc_id)}")
    print(f"\n  Total: {passed}/{total} passed")
    if passed == total:
        print("  🎉 ALL TESTS PASSED!")
    elif passed >= total - 1:
        print("  ⚠️  Nearly all passed — check failures above")
    else:
        print("  ❌ Multiple failures — review above")

    return passed == total


if __name__ == "__main__":
    rc = 0 if asyncio.run(main()) else 1
    sys.exit(rc)
