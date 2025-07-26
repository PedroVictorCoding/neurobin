"""
Pathway Effects Computation Script
Computes compound pathway effects based on compound-target interactions and target-pathway mappings.
This should be run after the main data population script.
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from compounds.models import (
    Compound, Target, CompoundTargetInteraction, 
    TargetPathwayInteraction, CompoundPathwayEffect
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Compute compound pathway effects from interactions and pathway data'
    
    def __init__(self):
        super().__init__()
        self.stats = {
            'effects_created': 0,
            'effects_updated': 0,
            'compounds_processed': 0,
            'pathways_processed': 0,
            'errors': 0
        }
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Batch size for processing compounds'
        )
        parser.add_argument(
            '--recompute',
            action='store_true',
            help='Recompute existing pathway effects'
        )
    
    def handle(self, *args, **options):
        """Main execution method"""
        start_time = timezone.now()
        
        self.stdout.write("🧠 COMPUTING PATHWAY EFFECTS")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Started at: {start_time}")
        self.stdout.write("")
        
        try:
            self.compute_all_pathway_effects(options)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⚠️  Process interrupted by user"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Fatal error: {e}"))
            logger.exception("Fatal error in pathway effects computation")
            self.stats['errors'] += 1
        finally:
            self.print_summary(start_time)
    
    def compute_all_pathway_effects(self, options):
        """Compute pathway effects for all compounds"""
        
        # Get compounds that have target interactions
        compounds_with_interactions = Compound.objects.filter(
            compoundtargetinteraction__isnull=False
        ).distinct()
        
        total_compounds = compounds_with_interactions.count()
        self.stdout.write(f"Processing {total_compounds} compounds with target interactions...")
        
        batch_size = options['batch_size']
        processed = 0
        
        for compound in compounds_with_interactions.iterator():
            try:
                self.compute_compound_pathway_effects(compound, options)
                processed += 1
                self.stats['compounds_processed'] += 1
                
                if processed % batch_size == 0:
                    self.stdout.write(f"  Processed {processed}/{total_compounds} compounds...")
            
            except Exception as e:
                logger.error(f"Error processing compound {compound.chembl_id}: {e}")
                self.stats['errors'] += 1
        
        self.stdout.write(f"✅ Completed processing {processed} compounds")
    
    def compute_compound_pathway_effects(self, compound, options):
        """Compute pathway effects for a specific compound"""
        
        # Get all target interactions for this compound
        target_interactions = CompoundTargetInteraction.objects.filter(
            compound=compound
        ).select_related('target')
        
        for interaction in target_interactions:
            target = interaction.target
            
            # Get all pathways for this target
            pathway_interactions = TargetPathwayInteraction.objects.filter(
                target=target
            )
            
            for pathway_interaction in pathway_interactions:
                try:
                    self.create_or_update_pathway_effect(
                        compound, 
                        pathway_interaction, 
                        interaction, 
                        options
                    )
                except Exception as e:
                    logger.error(f"Error creating pathway effect: {e}")
                    self.stats['errors'] += 1
    
    def create_or_update_pathway_effect(self, compound, pathway_interaction, target_interaction, options):
        """Create or update a compound pathway effect"""
        
        # Check if effect already exists
        if not options['recompute']:
            existing = CompoundPathwayEffect.objects.filter(
                compound=compound,
                pathway=pathway_interaction,
                inferred_from=target_interaction.target
            ).exists()
            
            if existing:
                return
        
        # Predict effect type based on mechanism and pathway
        effect_type = self.predict_effect_type(
            target_interaction.mechanism_of_action,
            pathway_interaction.pathway_name
        )
        
        # Calculate confidence based on interaction and pathway confidence
        confidence = self.calculate_confidence(
            target_interaction.confidence,
            pathway_interaction.confidence
        )
        
        # Calculate strength based on mechanism type
        strength = self.calculate_strength(target_interaction.mechanism_of_action)
        
        # Create or update the pathway effect
        effect, created = CompoundPathwayEffect.objects.update_or_create(
            compound=compound,
            pathway=pathway_interaction,
            inferred_from=target_interaction.target,
            defaults={
                'mechanism': target_interaction.mechanism_of_action,
                'effect_type': effect_type,
                'confidence': confidence,
                'strength': strength,
                'created_at': timezone.now()
            }
        )
        
        if created:
            self.stats['effects_created'] += 1
        else:
            self.stats['effects_updated'] += 1
        
        self.stats['pathways_processed'] += 1
    
    def predict_effect_type(self, mechanism, pathway_name):
        """Predict effect type based on mechanism and pathway"""
        
        mechanism = mechanism.lower() if mechanism else ''
        pathway_name = pathway_name.lower() if pathway_name else ''
        
        # Define mechanism categories
        activating_mechanisms = [
            'agonist', 'activator', 'opener', 'enhancer', 'stimulator',
            'positive modulator', 'pam', 'facilitator'
        ]
        
        inhibiting_mechanisms = [
            'antagonist', 'inhibitor', 'blocker', 'suppressor',
            'negative modulator', 'nam', 'reducer'
        ]
        
        modulating_mechanisms = [
            'modulator', 'regulator', 'stabilizer', 'chaperone'
        ]
        
        # Check mechanism type
        if any(term in mechanism for term in activating_mechanisms):
            base_effect = 'activating'
        elif any(term in mechanism for term in inhibiting_mechanisms):
            base_effect = 'inhibiting'
        elif any(term in mechanism for term in modulating_mechanisms):
            base_effect = 'modulating'
        else:
            base_effect = 'unknown'
        
        # Adjust based on pathway context
        inhibitory_pathways = [
            'degradation', 'breakdown', 'catabolism', 'inhibition',
            'repression', 'silencing', 'apoptosis', 'death'
        ]
        
        if any(term in pathway_name for term in inhibitory_pathways):
            # Flip effect for inhibitory pathways
            if base_effect == 'activating':
                return 'inhibiting'
            elif base_effect == 'inhibiting':
                return 'activating'
        
        return base_effect
    
    def calculate_confidence(self, interaction_confidence, pathway_confidence):
        """Calculate overall confidence based on interaction and pathway confidence"""
        
        # Convert confidence levels to numeric values
        confidence_values = {
            'high': 3,
            'medium': 2,
            'low': 1
        }
        
        interaction_val = confidence_values.get(interaction_confidence.lower(), 1)
        pathway_val = confidence_values.get(pathway_confidence.lower(), 1)
        
        # Calculate average and convert back
        average = (interaction_val + pathway_val) / 2
        
        if average >= 2.5:
            return 'high'
        elif average >= 1.5:
            return 'medium'
        else:
            return 'low'
    
    def calculate_strength(self, mechanism):
        """Calculate effect strength based on mechanism type"""
        
        mechanism = mechanism.lower() if mechanism else ''
        
        # Strong effects
        strong_mechanisms = [
            'agonist', 'antagonist', 'inhibitor', 'activator',
            'full agonist', 'competitive antagonist'
        ]
        
        # Moderate effects
        moderate_mechanisms = [
            'partial agonist', 'modulator', 'enhancer', 'weak',
            'non-competitive', 'allosteric'
        ]
        
        # Weak effects
        weak_mechanisms = [
            'inverse agonist', 'partial', 'mild', 'indirect'
        ]
        
        if any(term in mechanism for term in strong_mechanisms):
            return 0.8
        elif any(term in mechanism for term in moderate_mechanisms):
            return 0.6
        elif any(term in mechanism for term in weak_mechanisms):
            return 0.4
        else:
            return 0.5  # Default moderate strength
    
    def print_summary(self, start_time):
        """Print operation summary"""
        end_time = timezone.now()
        duration = end_time - start_time
        
        self.stdout.write("")
        self.stdout.write("📊 PATHWAY EFFECTS COMPUTATION SUMMARY")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Duration: {duration}")
        self.stdout.write("")
        self.stdout.write(f"Compounds processed: {self.stats['compounds_processed']:,}")
        self.stdout.write(f"Pathway effects created: {self.stats['effects_created']:,}")
        self.stdout.write(f"Pathway effects updated: {self.stats['effects_updated']:,}")
        self.stdout.write(f"Total pathways processed: {self.stats['pathways_processed']:,}")
        self.stdout.write(f"Errors: {self.stats['errors']:,}")
        self.stdout.write("")
        
        # Final database counts
        total_effects = CompoundPathwayEffect.objects.count()
        self.stdout.write(f"Total pathway effects in database: {total_effects:,}")
        
        if self.stats['errors'] == 0:
            self.stdout.write(self.style.SUCCESS("✅ Pathway effects computation completed successfully!"))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️  Completed with {self.stats['errors']} errors"))
