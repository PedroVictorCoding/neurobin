from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('compounds', '0043_ester_ratio'),
    ]

    operations = [
        migrations.AddField(
            model_name='compound',
            name='standard_dose',
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                help_text='Typical therapeutic or standard human dose (e.g. 5 for Donepezil 5mg)',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='compound',
            name='standard_dose_unit',
            field=models.CharField(
                blank=True,
                default='mg',
                help_text='Unit for standard_dose (mg, mcg, g, IU, etc.)',
                max_length=16,
            ),
        ),
    ]
