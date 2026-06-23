#!/usr/bin/env python3
"""Verify Jinja2 syntax for all templates."""

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
import sys
from pathlib import Path

# Templates to verify (prioritized list + others)
TEMPLATES_TO_CHECK = [
    'home.html',
    'products.html',
    'tools.html',
    'order.html',
    'measurements.html',
    'contact.html',
    'tutorial.html',
    'privacy.html',
    'terms.html',
]

def verify_templates():
    """Load and compile all templates to check for syntax errors."""
    template_dir = Path(__file__).parent / 'templates'
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    results = {}
    all_passed = True

    for template_name in TEMPLATES_TO_CHECK:
        template_path = template_dir / template_name
        if not template_path.exists():
            results[template_name] = f'SKIP (file not found)'
            continue

        try:
            # Attempt to load and compile the template
            env.get_template(template_name)
            results[template_name] = 'PASS'
        except TemplateSyntaxError as e:
            results[template_name] = f'FAIL: {e.message} (line {e.lineno})'
            all_passed = False
        except Exception as e:
            results[template_name] = f'ERROR: {str(e)}'
            all_passed = False

    # Print results
    print("=" * 70)
    print("JINJA2 TEMPLATE VERIFICATION")
    print("=" * 70)
    for name, status in results.items():
        symbol = "✓" if status == "PASS" else "✗" if status.startswith("FAIL") else "~"
        print(f"{symbol} {name:30s} {status}")
    print("=" * 70)

    if all_passed:
        print("\n✓ All templates passed Jinja2 syntax check!")
        return 0
    else:
        print("\n✗ Some templates have syntax errors. Fix before committing.")
        return 1

if __name__ == '__main__':
    sys.exit(verify_templates())
