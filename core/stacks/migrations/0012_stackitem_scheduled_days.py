from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stacks', '0011_stacktrait_stackdangerouspairrule_mechanismtraitrule'),
    ]

    operations = [
        migrations.AddField(
            model_name='stackitem',
            name='scheduled_days',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Comma-separated weekday numbers (0=Mon \u2026 6=Sun). E.g. '0,2,4' = Mon/Wed/Fri.",
                max_length=20,
            ),
        ),
    ]
