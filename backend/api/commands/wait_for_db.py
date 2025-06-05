# backend/api/management/commands/wait_for_db.py
import time
from django.db import connections
from django.db.utils import OperationalError
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    """Django command to pause execution until database is available"""

    def handle(self, *args, **options):
        self.stdout.write("Waiting for database...")
        db_conn = None
        max_retries = options.get('retries', 30) # Number of retries
        retry_delay = options.get('delay', 2)   # Delay between retries in seconds
        retries_count = 0

        while not db_conn and retries_count < max_retries:
            try:
                db_conn = connections['default']
                db_conn.cursor() # Try to get a cursor to check connection
            except OperationalError:
                self.stdout.write("Database unavailable, waiting {} second(s)...".format(retry_delay))
                time.sleep(retry_delay)
                retries_count +=1
            except Exception as e: # Catch any other potential connection errors
                self.stderr.write(f"An unexpected error occurred while connecting to DB: {e}")
                time.sleep(retry_delay)
                retries_count +=1

        if db_conn:
            self.stdout.write(self.style.SUCCESS("Database available!"))
        else:
            self.stderr.write(self.style.ERROR(f"Database unavailable after {max_retries} retries. Exiting."))
            # Optionally exit with an error code if needed for CI/CD
            # import sys
            # sys.exit(1)

    def add_arguments(self, parser):
        parser.add_argument(
            '--retries',
            type=int,
            default=30,
            help='Number of times to retry connecting to the database.'
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=2,
            help='Delay in seconds between retries.'
        )
