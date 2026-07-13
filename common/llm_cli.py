#!/usr/bin/env python3
import sys
import os
import argparse

# Add current directory to path to ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_utils import get_client

def main():
    parser = argparse.ArgumentParser(description="LLM / Vertex Unified CLI Client")
    parser.add_argument("prompt", nargs="?", help="The prompt text to send to the model.")
    parser.add_argument("-m", "--model", default="gemini-3.1-flash-lite-preview", 
                        help="Model name (default: gemini-3.1-flash-lite-preview)")
    parser.add_argument("-p", "--provider", default=None, 
                        help="Provider override (e.g., vertex, gemini, dashscope)")
    
    args = parser.parse_args()

    # Read from stdin if piped (with non-blocking check to avoid hanging in subprocess)
    prompt = args.prompt
    if not sys.stdin.isatty():
        # Cross-platform non-blocking stdin read (select is Unix-only)
        import threading
        stdin_content = [None]
        def _read_stdin():
            try:
                stdin_content[0] = sys.stdin.read().strip()
            except Exception:
                pass
        t = threading.Thread(target=_read_stdin, daemon=True)
        t.start()
        t.join(timeout=2.0)
        if stdin_content[0]:
            if prompt:
                prompt = f"{prompt}\n\n[Input Context]:\n{stdin_content[0]}"
            else:
                prompt = stdin_content[0]

    if not prompt:
        parser.print_help()
        sys.exit(0)

    try:
        client = get_client()
        from llm_utils import LLMProvider
        # Default to Vertex; bypass ordered_configs which may contain broken project creds from .env
        provider_enum = LLMProvider.VERTEX
        if args.provider:
            try:
                provider_enum = LLMProvider(args.provider.lower())
            except ValueError:
                print(f"Error: Unknown provider '{args.provider}'", file=sys.stderr)
                sys.exit(1)

        result = client.generate_content(
            content=prompt,
            model_name=args.model,
            provider=provider_enum,
            fallback=False
        )
        if result:
            print(result)
        else:
            print("Error: Empty response from model.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error calling model: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
