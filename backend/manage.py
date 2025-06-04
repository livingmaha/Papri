#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Set DJANGO_SETTINGS_MODULE, prioritizing .env if it sets it,
    # then environment variable, then default.
    # However, Celery and other tools often expect it to be set before they run.
    # For manage.py, it's typically set here or by the environment.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'papri_project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
