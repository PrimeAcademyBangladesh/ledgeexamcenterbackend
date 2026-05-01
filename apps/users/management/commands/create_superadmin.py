import os

from django.core.management.base import BaseCommand

from apps.users.models import Role, User


class Command(BaseCommand):
    help = "Create the default superadmin from environment variables. Safe to run multiple times."

    def handle(self, *args, **options):
        email = os.environ.get("SUPERADMIN_EMAIL")
        password = os.environ.get("SUPERADMIN_PASSWORD")
        first_name = os.environ.get("SUPERADMIN_FIRST_NAME", "Super")
        last_name = os.environ.get("SUPERADMIN_LAST_NAME", "Admin")

        if not email or not password:
            self.stderr.write(self.style.ERROR(
                "SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD must be set in the environment."
            ))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f"Superadmin '{email}' already exists — skipped."))
            return

        User.objects.create_superuser(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=Role.ADMIN,
        )
        self.stdout.write(self.style.SUCCESS(f"Superadmin '{email}' created successfully."))
