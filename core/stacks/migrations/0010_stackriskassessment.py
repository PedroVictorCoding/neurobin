from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("stacks", "0009_stack_views"),
    ]

    operations = [
        migrations.CreateModel(
            name="StackRiskAssessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("input_hash", models.CharField(db_index=True, max_length=64)),
                ("compound_count", models.PositiveIntegerField(default=0)),
                ("predicted_count", models.PositiveIntegerField(default=0)),
                ("risk_score", models.FloatField(blank=True, null=True)),
                (
                    "risk_level",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("low", "Low"),
                            ("moderate", "Moderate"),
                            ("high", "High"),
                        ],
                        default="unknown",
                        max_length=10,
                    ),
                ),
                ("details", models.JSONField(blank=True, default=dict)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                (
                    "stack",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="risk_assessment",
                        to="stacks.stack",
                    ),
                ),
            ],
            options={
                "ordering": ["-computed_at"],
            },
        ),
    ]

