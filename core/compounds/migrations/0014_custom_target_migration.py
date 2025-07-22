# Custom migration to handle target_name conversion to ForeignKey
import django.db.models.deletion
from django.db import migrations, models


def convert_target_names_to_targets(apps, schema_editor):
    """Convert existing target_name strings to Target objects"""
    CompoundMechanismOfAction = apps.get_model('compounds', 'CompoundMechanismOfAction')
    Target = apps.get_model('compounds', 'Target')
    
    # Get all unique target names that are not empty
    existing_mechanisms = CompoundMechanismOfAction.objects.exclude(target_name='').exclude(target_name__isnull=True)
    
    target_names = set()
    for mechanism in existing_mechanisms:
        if mechanism.target_name and mechanism.target_name.strip():
            target_names.add(mechanism.target_name.strip())
    
    # Create Target objects for each unique name
    for name in target_names:
        Target.objects.get_or_create(name=name)


def reverse_target_conversion(apps, schema_editor):
    """Reverse the conversion (not fully reversible, but prevent errors)"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('compounds', '0013_delete_compoundtargetinteraction_delete_targets'),
    ]

    operations = [
        # First create the Target model
        migrations.CreateModel(
            name='Target',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the target (e.g., GABA-A receptor, Dopamine transporter)', max_length=255, unique=True)),
            ],
            options={
                'verbose_name': 'Target',
                'verbose_name_plural': 'Targets',
                'ordering': ['name'],
            },
        ),
        
        # Create Target objects from existing target_name values
        migrations.RunPython(convert_target_names_to_targets, reverse_target_conversion),
        
        # Add the new ForeignKey field (nullable initially)
        migrations.AddField(
            model_name='compoundmechanismofaction',
            name='target_name_fk',
            field=models.ForeignKey(blank=True, help_text='Target this mechanism acts on', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mechanisms', to='compounds.target'),
        ),
    ]
