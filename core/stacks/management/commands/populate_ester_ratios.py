"""
Management command: populate_ester_ratios
-----------------------------------------
Seeds CompoundSteroidRating.ester_ratio for all known AAS ester compounds.

ester_ratio = free_base_MW / ester_compound_MW
  · 1.0  →  oral / ester-free compound (no correction needed)
  · <1.0 →  ester mass reduces the fraction of active hormone per mg

Used by the stack builder to convert user-entered ester doses to free-base
equivalents before comparing against the compound's standard dose.

Molecular weights sourced from PubChem / USP monographs.

Usage:
  python manage.py populate_ester_ratios
  python manage.py populate_ester_ratios --dry-run
  python manage.py populate_ester_ratios --overwrite
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from compounds.models import Compound, CompoundSteroidRating

# ---------------------------------------------------------------------------
# Ester ratio profiles
# 'names'  – lowercase substrings; matches if compound name icontains ANY
# 'ratio'  – free_base_MW / ester_compound_MW  (1.0 for non-esterified)
#
# Free-base / oral compounds intentionally omitted — their DB default of 1.0
# is already correct.
# ---------------------------------------------------------------------------
PROFILES: list[dict] = [

    # ── TESTOSTERONE ESTERS ───────────────────────────────────────────────────
    # Testosterone free base MW = 288.42
    {'names': ['testosterone enanthate'],          'ratio': 0.7200},  # MW 400.60
    {'names': ['testosterone cypionate'],          'ratio': 0.6990},  # MW 412.61
    {'names': ['testosterone propionate'],         'ratio': 0.8373},  # MW 344.49
    {'names': ['testosterone undecanoate'],        'ratio': 0.6315},  # MW 456.70
    {'names': ['testosterone suspension'],         'ratio': 1.0000},  # aqueous free base
    {'names': ['testosterone decanoate'],          'ratio': 0.6520},  # MW 442.68
    {'names': ['testosterone isocaproate'],        'ratio': 0.7458},  # MW 386.58
    {'names': ['testosterone phenylpropionate'],   'ratio': 0.7086},  # MW 406.57
    {'names': ['testosterone acetate'],            'ratio': 0.8672},  # MW 332.46
    {'names': ['testosterone buciclate'],          'ratio': 0.5755},  # MW 501.72
    {'names': ['testosterone ketolaurate'],        'ratio': 0.5698},  # MW 506.73

    # ── NANDROLONE ESTERS ─────────────────────────────────────────────────────
    # Nandrolone free base MW = 274.40
    {'names': ['nandrolone decanoate'],            'ratio': 0.6400},  # MW 428.65
    {'names': ['nandrolone phenylpropionate',
               'nandrolone phenpropionate'],       'ratio': 0.6749},  # MW 406.57
    {'names': ['nandrolone undecanoate'],          'ratio': 0.6200},  # MW 442.67
    {'names': ['nandrolone laurate'],              'ratio': 0.6100},  # MW 449.70
    {'names': ['nandrolone cypionate'],            'ratio': 0.6897},  # MW 397.60

    # ── BOLDENONE ESTERS ──────────────────────────────────────────────────────
    # Boldenone free base MW = 286.41
    {'names': ['boldenone undecylenate'],          'ratio': 0.6327},  # MW 452.67
    {'names': ['boldenone cypionate'],             'ratio': 0.7224},  # MW 396.56

    # ── TRENBOLONE ESTERS ─────────────────────────────────────────────────────
    # Trenbolone free base MW = 270.37
    {'names': ['trenbolone acetate'],              'ratio': 0.8655},  # MW 312.41
    {'names': ['trenbolone enanthate'],            'ratio': 0.7067},  # MW 382.54
    {'names': ['trenbolone hexahydrobenzylcarbonate',
               'trenbolone cyclohexylmethylcarbonate'],
                                                   'ratio': 0.5795},  # MW 466.62

    # ── DROSTANOLONE ESTERS ───────────────────────────────────────────────────
    # Drostanolone free base MW = 304.47
    {'names': ['drostanolone propionate'],         'ratio': 0.8446},  # MW 360.53
    {'names': ['drostanolone enanthate'],          'ratio': 0.7308},  # MW 416.64

    # ── METHENOLONE ESTERS ────────────────────────────────────────────────────
    # Methenolone free base MW = 302.46
    {'names': ['methenolone enanthate'],           'ratio': 0.7295},  # MW 414.62
    {'names': ['methenolone acetate'],             'ratio': 0.8780},  # MW 344.49

    # ── TRESTOLONE ESTERS ─────────────────────────────────────────────────────
    # Trestolone free base MW = 302.46
    {'names': ['trestolone acetate'],              'ratio': 0.8780},  # MW 344.49
    {'names': ['trestolone enanthate'],            'ratio': 0.7295},  # MW 414.62

    # ── CLOSTEBOL ESTERS ──────────────────────────────────────────────────────
    # Clostebol free base MW = 322.84
    {'names': ['clostebol acetate'],               'ratio': 0.8848},  # MW 364.87
    {'names': ['clostebol propionate'],            'ratio': 0.8565},  # MW 376.90

    # ── OXANDROLONE / STANOZOLOL – no common ester forms, ratio stays 1.0 ───

]


def _apply_profile(profile: dict, dry_run: bool, overwrite: bool, stdout) -> tuple[int, int]:
    set_count = skipped = 0
    for name_frag in profile['names']:
        qs = Compound.objects.filter(name__icontains=name_frag)
        for compound in qs:
            rating, _ = CompoundSteroidRating.objects.get_or_create(compound=compound)
            if not overwrite and float(rating.ester_ratio) != 1.0:
                skipped += 1
                continue
            if dry_run:
                stdout.write(f'  [dry] {compound.name}: ester_ratio → {profile["ratio"]}')
                continue
            rating.ester_ratio = profile['ratio']
            rating.save(update_fields=['ester_ratio'])
            set_count += 1
    return set_count, skipped


class Command(BaseCommand):
    help = 'Seed CompoundSteroidRating.ester_ratio for known AAS ester compounds.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--overwrite', action='store_true',
                            help='Replace existing non-1.0 values.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        overwrite = options['overwrite']
        total_set = total_skipped = 0

        with transaction.atomic():
            for profile in PROFILES:
                s, sk = _apply_profile(profile, dry_run, overwrite, self.stdout)
                total_set += s
                total_skipped += sk

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes written.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Done.  Set: {total_set}  Skipped (already non-1.0): {total_skipped}'
                )
            )
