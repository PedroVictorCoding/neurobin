from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("compounds", "0028_remove_pathway_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompoundADMETPrediction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("smiles", models.CharField(max_length=1000)),
                ("smiles_sha256", models.CharField(max_length=64)),
                ("model_version", models.CharField(blank=True, max_length=64)),
                ("predictions", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                (
                    "compound",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="admet_ai_prediction",
                        to="compounds.compound",
                    ),
                ),
            ],
            options={
                "ordering": ["-computed_at"],
            },
        ),
        migrations.AddIndex(
            model_name="compoundadmetprediction",
            index=models.Index(fields=["computed_at"], name="comp_admet_computed_at_idx"),
        ),
    ]
