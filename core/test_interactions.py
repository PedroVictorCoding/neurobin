#!/usr/bin/env python
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound, Target, CompoundTargetInteraction, CompoundToCompoundTargetInteraction
from django.db import models

def create_test_data():
    """Create sample compound interaction data for testing"""
    
    # Create compounds
    caffeine, _ = Compound.objects.get_or_create(
        name="Caffeine", 
        defaults={'description': 'Central nervous system stimulant that blocks adenosine receptors'}
    )
    
    modafinil, _ = Compound.objects.get_or_create(
        name="Modafinil", 
        defaults={'description': 'Wakefulness-promoting agent that affects dopamine'}
    )
    
    fluoxetine, _ = Compound.objects.get_or_create(
        name="Fluoxetine", 
        defaults={'description': 'SSRI antidepressant that inhibits serotonin reuptake'}
    )
    
    # Create targets
    adenosine_a2a, _ = Target.objects.get_or_create(
        name="Adenosine A2A receptor", 
        defaults={
            'type': 'receptor', 
            'description': 'G-protein coupled receptor involved in sleep regulation'
        }
    )
    
    cyp2d6, _ = Target.objects.get_or_create(
        name="CYP2D6", 
        defaults={
            'type': 'enzyme', 
            'description': 'Cytochrome P450 2D6 enzyme responsible for drug metabolism'
        }
    )
    
    dopamine_transporter, _ = Target.objects.get_or_create(
        name="Dopamine transporter", 
        defaults={
            'type': 'transporter', 
            'description': 'Protein responsible for dopamine reuptake'
        }
    )
    
    serotonin_transporter, _ = Target.objects.get_or_create(
        name="Serotonin transporter", 
        defaults={
            'type': 'transporter', 
            'description': 'Protein responsible for serotonin reuptake'
        }
    )
    
    # Create compound-target interactions
    caffeine_adenosine, _ = CompoundTargetInteraction.objects.get_or_create(
        compound=caffeine,
        target=adenosine_a2a,
        mechanism='antagonist',
        defaults={
            'affinity_level': 'high',
            'notes': 'Caffeine blocks adenosine A2A receptors, preventing drowsiness'
        }
    )
    
    modafinil_dat, _ = CompoundTargetInteraction.objects.get_or_create(
        compound=modafinil,
        target=dopamine_transporter,
        mechanism='inhibitor',
        defaults={
            'affinity_level': 'moderate',
            'notes': 'Modafinil blocks dopamine reuptake, increasing alertness'
        }
    )
    
    fluoxetine_sert, _ = CompoundTargetInteraction.objects.get_or_create(
        compound=fluoxetine,
        target=serotonin_transporter,
        mechanism='inhibitor',
        defaults={
            'affinity_level': 'very_high',
            'notes': 'Fluoxetine is a selective serotonin reuptake inhibitor'
        }
    )
    
    fluoxetine_cyp2d6, _ = CompoundTargetInteraction.objects.get_or_create(
        compound=fluoxetine,
        target=cyp2d6,
        mechanism='inhibitor',
        defaults={
            'affinity_level': 'high',
            'notes': 'Fluoxetine strongly inhibits CYP2D6 enzyme'
        }
    )
    
    modafinil_cyp2d6, _ = CompoundTargetInteraction.objects.get_or_create(
        compound=modafinil,
        target=cyp2d6,
        mechanism='substrate',
        defaults={
            'affinity_level': 'moderate',
            'notes': 'Modafinil is metabolized by CYP2D6'
        }
    )
    
    # Create compound-to-compound interactions
    try:
        fluoxetine_modafinil_interaction, created = CompoundToCompoundTargetInteraction.objects.get_or_create(
            compound_a=fluoxetine,
            compound_b=modafinil,
            target=cyp2d6,
            defaults={
                'interaction_type': 'enzyme_inhibition',
                'description': 'Fluoxetine inhibits CYP2D6, which can slow the metabolism of modafinil, potentially increasing its effects and duration.',
                'confidence': 'high',
                'source': 'Clinical pharmacology studies'
            }
        )
        if created:
            print("Created fluoxetine-modafinil interaction")
        else:
            print("Fluoxetine-modafinil interaction already exists")
    except Exception as e:
        print(f"Error creating interaction: {e}")
        # Try to find existing interaction
        existing = CompoundToCompoundTargetInteraction.objects.filter(
            target=cyp2d6
        ).filter(
            models.Q(compound_a=fluoxetine, compound_b=modafinil) |
            models.Q(compound_a=modafinil, compound_b=fluoxetine)
        ).first()
        if existing:
            print("Found existing interaction between fluoxetine and modafinil")
    
    print("✅ Test data created successfully!")
    print(f"Compounds: {Compound.objects.count()}")
    print(f"Targets: {Target.objects.count()}")
    print(f"Compound-Target Interactions: {CompoundTargetInteraction.objects.count()}")
    print(f"Compound-Compound Interactions: {CompoundToCompoundTargetInteraction.objects.count()}")

if __name__ == "__main__":
    create_test_data()
