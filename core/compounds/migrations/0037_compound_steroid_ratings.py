from django.db import migrations, models
import django.db.models.deletion


def forwards_copy_ratings(apps, schema_editor):
    Compound = apps.get_model('compounds', 'Compound')
    CompoundSteroidRating = apps.get_model('compounds', 'CompoundSteroidRating')

    for compound in Compound.objects.exclude(
        anabolic_rating__isnull=True,
        androgenic_rating__isnull=True,
    ):
        CompoundSteroidRating.objects.update_or_create(
            compound=compound,
            defaults={
                'anabolic_rating': compound.anabolic_rating,
                'androgenic_rating': compound.androgenic_rating,
            },
        )


def backwards_copy_ratings(apps, schema_editor):
    Compound = apps.get_model('compounds', 'Compound')
    CompoundSteroidRating = apps.get_model('compounds', 'CompoundSteroidRating')

    for rating in CompoundSteroidRating.objects.select_related('compound'):
        Compound.objects.filter(pk=rating.compound_id).update(
            anabolic_rating=rating.anabolic_rating,
            androgenic_rating=rating.androgenic_rating,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('compounds', '0036_compound_anabolic_rating_compound_androgenic_rating'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompoundSteroidRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anabolic_rating', models.DecimalField(blank=True, decimal_places=2, help_text='Relative anabolic rating (commonly testosterone=100 baseline).', max_digits=7, null=True)),
                ('androgenic_rating', models.DecimalField(blank=True, decimal_places=2, help_text='Relative androgenic rating (commonly testosterone=100 baseline).', max_digits=7, null=True)),
                ('compound', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='steroid_ratings', to='compounds.compound')),
            ],
        ),
        migrations.RunPython(forwards_copy_ratings, backwards_copy_ratings),
        migrations.RemoveField(
            model_name='compound',
            name='anabolic_rating',
        ),
        migrations.RemoveField(
            model_name='compound',
            name='androgenic_rating',
        ),
    ]
