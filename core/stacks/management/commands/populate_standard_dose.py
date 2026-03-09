"""
Management command: populate_standard_dose
------------------------------------------
Seeds Compound.standard_dose / standard_dose_unit for all key compounds
in the stack builder using published pharmacological / clinical literature.

FOR AAS INJECTABLES: standard_dose is stored as the FREE-BASE equivalent
(not the ester dose the user enters).  The stack builder multiplies the
user-entered ester dose by ester_ratio (from CompoundSteroidRating) to get
the free-base mg before comparing to this value.  This allows accurate
dose-relative risk scaling across different esters of the same hormone.

For all other compounds standard_dose is the typical single dose in the
stated unit (mg/mcg/IU).

Units: mg (default), mcg, IU, g

Usage:
  python manage.py populate_standard_dose
  python manage.py populate_standard_dose --dry-run
  python manage.py populate_standard_dose --overwrite   # replace existing values
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from compounds.models import Compound

# ---------------------------------------------------------------------------
# Dose profiles
# 'names'  – list of lowercase substrings; a compound matches if its name
#             contains ANY of these (case-insensitive)
# 'dose'   – standard single dose value (numeric)
# 'unit'   – 'mg' | 'mcg' | 'IU' | 'g'
# ---------------------------------------------------------------------------
PROFILES: list[dict] = [

    # ── ANDROGENS / AAS – INJECTABLE ─────────────────────────────────────────
    # Doses are in FREE-BASE equivalents. The builder applies ester_ratio to
    # convert the user's ester mg to free-base mg before comparing here.
    # All testosterone esters share the same free-base standard (100 mg TRT).
    {'names': ['testosterone enanthate',
               'testosterone cypionate',
               'testosterone propionate',
               'testosterone undecanoate',
               'testosterone suspension',
               'testosterone decanoate',
               'testosterone isocaproate',
               'testosterone phenylpropionate',
               'testosterone acetate'],            'dose': 100,   'unit': 'mg'},
    # base / free testosterone
    {'names': ['testosterone'],                    'dose': 100,   'unit': 'mg'},
    # Sustanon is a blend; ~180 mg free test per 250 mg dose → use 100 mg base
    {'names': ['sustanon'],                        'dose': 100,   'unit': 'mg'},
    # Nandrolone: standard ~100 mg/week free base
    {'names': ['nandrolone decanoate',
               'nandrolone phenylpropionate',
               'nandrolone undecanoate',
               'nandrolone cypionate',
               'nandrolone laurate'],              'dose': 100,   'unit': 'mg'},
    {'names': ['nandrolone'],                      'dose': 100,   'unit': 'mg'},
    # Boldenone: standard ~150 mg/week free base
    {'names': ['boldenone undecylenate',
               'boldenone cypionate'],             'dose': 150,   'unit': 'mg'},
    {'names': ['boldenone'],                       'dose': 150,   'unit': 'mg'},
    # Trenbolone: very potent — standard ~50 mg/week free base
    {'names': ['trenbolone acetate',
               'trenbolone enanthate',
               'trenbolone hexahydrobenzylcarbonate',
               'trenbolone cyclohexylmethylcarbonate'], 'dose': 50, 'unit': 'mg'},
    {'names': ['trenbolone'],                      'dose': 50,    'unit': 'mg'},
    # Drostanolone: standard ~75 mg/week free base
    {'names': ['drostanolone propionate',
               'drostanolone enanthate'],          'dose': 75,    'unit': 'mg'},
    {'names': ['drostanolone'],                    'dose': 75,    'unit': 'mg'},
    # Methenolone (Primobolan): injectable standard ~200 mg/week free base
    {'names': ['methenolone enanthate'],           'dose': 200,   'unit': 'mg'},
    # Methenolone oral (acetate): ~20 mg/day free base
    {'names': ['methenolone acetate'],             'dose': 20,    'unit': 'mg'},
    {'names': ['methenolone'],                     'dose': 100,   'unit': 'mg'},
    # Trestolone: extremely potent — standard ~20 mg/week free base
    {'names': ['trestolone acetate',
               'trestolone enanthate', 'ment '],   'dose': 20,    'unit': 'mg'},
    {'names': ['trestolone'],                      'dose': 20,    'unit': 'mg'},
    # Clostebol: mild androgen — standard ~5 mg/day free base
    {'names': ['clostebol acetate',
               'clostebol propionate'],            'dose': 5,     'unit': 'mg'},
    {'names': ['clostebol'],                       'dose': 5,     'unit': 'mg'},
    {'names': ['epitestosterone'],                 'dose': 20,    'unit': 'mg'},

    # ── ANDROGENS / AAS – ORAL 17α-ALKYLATED ─────────────────────────────────
    {'names': ['stanozolol'],                      'dose': 50,    'unit': 'mg'},
    {'names': ['oxandrolone'],                     'dose': 40,    'unit': 'mg'},
    {'names': ['methandrostenolone',
               'methandienone'],                   'dose': 30,    'unit': 'mg'},
    {'names': ['oxymetholone'],                    'dose': 50,    'unit': 'mg'},
    {'names': ['fluoxymesterone'],                 'dose': 10,    'unit': 'mg'},
    {'names': ['methyltestosterone'],              'dose': 25,    'unit': 'mg'},
    {'names': ['mesterolone'],                     'dose': 25,    'unit': 'mg'},
    {'names': ['methasterone', 'superdrol'],       'dose': 20,    'unit': 'mg'},
    {'names': ['dimethyltrienolone'],              'dose': 0.5,   'unit': 'mg'},
    {'names': ['gestrinone'],                      'dose': 5,     'unit': 'mg'},

    # ── SARMs ─────────────────────────────────────────────────────────────────
    {'names': ['ostarine', 'mk-2866', 'enobosarm'],'dose': 25,   'unit': 'mg'},
    {'names': ['ligandrol', 'lgd-4033',
               'lgd4033', 'vk5211'],               'dose': 10,    'unit': 'mg'},
    {'names': ['rad-140', 'rad140', 'testolone'],  'dose': 10,    'unit': 'mg'},
    {'names': ['andarine', 's-4 ', 's4 '],         'dose': 50,    'unit': 'mg'},
    {'names': ['yk11'],                            'dose': 10,    'unit': 'mg'},
    {'names': ['s23'],                             'dose': 20,    'unit': 'mg'},
    {'names': ['ac-262', 'ac262'],                 'dose': 10,    'unit': 'mg'},
    {'names': ['gsk2881078'],                      'dose': 1,     'unit': 'mg'},

    # ── PPAR / METABOLIC MODULATORS ───────────────────────────────────────────
    {'names': ['cardarine', 'gw501516',
               'gw-501516'],                       'dose': 10,    'unit': 'mg'},
    {'names': ['sr9009', 'stenabolic'],            'dose': 30,    'unit': 'mg'},
    {'names': ['ibutamoren', 'mk-677', 'mk677'],   'dose': 25,    'unit': 'mg'},

    # ── GH AXIS / SECRETAGOGUES ───────────────────────────────────────────────
    {'names': ['ipamorelin'],                      'dose': 200,   'unit': 'mcg'},
    {'names': ['sermorelin'],                      'dose': 200,   'unit': 'mcg'},
    {'names': ['cjc-1295', 'cjc1295'],             'dose': 1000,  'unit': 'mcg'},
    {'names': ['hexarelin'],                       'dose': 100,   'unit': 'mcg'},
    {'names': ['ghrp-2', 'ghrp2'],                 'dose': 100,   'unit': 'mcg'},
    {'names': ['ghrp-6', 'ghrp6'],                 'dose': 100,   'unit': 'mcg'},
    {'names': ['tesamorelin'],                     'dose': 2,     'unit': 'mg'},
    {'names': ['somatropin', 'somatotropin',
               'human growth hormone'],            'dose': 1,     'unit': 'IU'},
    {'names': ['mecasermin', 'igf-1',
               'insulin-like growth factor'],      'dose': 40,    'unit': 'mcg'},
    {'names': ['aod-9604', 'aod9604'],             'dose': 300,   'unit': 'mcg'},

    # ── REPAIR / TISSUE PEPTIDES ──────────────────────────────────────────────
    {'names': ['bpc-157', 'bpc157'],               'dose': 250,   'unit': 'mcg'},
    {'names': ['tb-500', 'tb500', 'thymosin beta'],'dose': 2,     'unit': 'mg'},
    {'names': ['ghk-cu', 'ghk copper',
               'copper peptide'],                  'dose': 200,   'unit': 'mcg'},
    {'names': ['mechano growth factor', 'mgf'],    'dose': 200,   'unit': 'mcg'},
    {'names': ['epithalon', 'epitalon'],           'dose': 5,     'unit': 'mg'},

    # ── ESTROGEN MODULATORS (AIs / SERMs) ─────────────────────────────────────
    {'names': ['anastrozole'],                     'dose': 0.5,   'unit': 'mg'},
    {'names': ['letrozole'],                       'dose': 2.5,   'unit': 'mg'},
    {'names': ['exemestane'],                      'dose': 25,    'unit': 'mg'},
    {'names': ['tamoxifen'],                       'dose': 20,    'unit': 'mg'},
    {'names': ['clomiphene', 'clomid'],            'dose': 50,    'unit': 'mg'},
    {'names': ['enclomiphene'],                    'dose': 25,    'unit': 'mg'},
    {'names': ['raloxifene'],                      'dose': 60,    'unit': 'mg'},
    {'names': ['fulvestrant'],                     'dose': 500,   'unit': 'mg'},
    {'names': ['toremifene'],                      'dose': 60,    'unit': 'mg'},
    {'names': ['4-hydroxytamoxifen', '4-ohta'],    'dose': 4,     'unit': 'mg'},

    # ── ANCILLARIES (prolactin / hCG) ─────────────────────────────────────────
    {'names': ['cabergoline'],                     'dose': 0.25,  'unit': 'mg'},
    {'names': ['bromocriptine'],                   'dose': 2.5,   'unit': 'mg'},
    {'names': ['chorionic gonadotropin', 'hcg'],   'dose': 500,   'unit': 'IU'},

    # ── NOOTROPICS / RACETAMS ─────────────────────────────────────────────────
    {'names': ['piracetam'],                       'dose': 1600,  'unit': 'mg'},
    {'names': ['aniracetam'],                      'dose': 750,   'unit': 'mg'},
    {'names': ['oxiracetam'],                      'dose': 800,   'unit': 'mg'},
    {'names': ['pramiracetam'],                    'dose': 400,   'unit': 'mg'},
    {'names': ['phenylpiracetam'],                 'dose': 100,   'unit': 'mg'},
    {'names': ['noopept',
               'n-phenylacetyl-l-prolylglycine'],  'dose': 10,    'unit': 'mg'},
    {'names': ['modafinil'],                       'dose': 200,   'unit': 'mg'},
    {'names': ['armodafinil'],                     'dose': 150,   'unit': 'mg'},
    {'names': ['vinpocetine'],                     'dose': 5,     'unit': 'mg'},
    {'names': ['huperzine'],                       'dose': 50,    'unit': 'mcg'},
    {'names': ['citicoline', 'cdp-choline'],       'dose': 250,   'unit': 'mg'},
    {'names': ['alpha-gpc', 'alpha gpc'],          'dose': 300,   'unit': 'mg'},
    {'names': ['semax'],                           'dose': 300,   'unit': 'mcg'},
    {'names': ['selank'],                          'dose': 250,   'unit': 'mcg'},
    {'names': ['cerebrolysin'],                    'dose': 5,     'unit': 'mg'},

    # ── SLEEP / CIRCADIAN ─────────────────────────────────────────────────────
    {'names': ['melatonin'],                       'dose': 0.5,   'unit': 'mg'},
    {'names': ['ramelteon'],                       'dose': 8,     'unit': 'mg'},
    {'names': ['agomelatine'],                     'dose': 25,    'unit': 'mg'},
    {'names': ['phenibut'],                        'dose': 500,   'unit': 'mg'},
    {'names': ['zolpidem'],                        'dose': 10,    'unit': 'mg'},
    {'names': ['eszopiclone'],                     'dose': 2,     'unit': 'mg'},
    {'names': ['zaleplon'],                        'dose': 10,    'unit': 'mg'},
    {'names': ['suvorexant'],                      'dose': 20,    'unit': 'mg'},
    {'names': ['lemborexant'],                     'dose': 5,     'unit': 'mg'},
    {'names': ['daridorexant'],                    'dose': 25,    'unit': 'mg'},
    {'names': ['sodium oxybate',
               'gamma-hydroxybutyrate', 'ghb'],    'dose': 4500,  'unit': 'mg'},

    # ── ADAPTOGENS ────────────────────────────────────────────────────────────
    {'names': ['ashwagandha', 'withania somnifera',
               'withanolide'],                     'dose': 300,   'unit': 'mg'},
    {'names': ['rhodiola'],                        'dose': 200,   'unit': 'mg'},
    {'names': ['panax ginseng', 'panax quinquefolius',
               'ginsenoside'],                     'dose': 200,   'unit': 'mg'},
    {'names': ['l-theanine'],                      'dose': 100,   'unit': 'mg'},
    {'names': ['phosphatidylserine'],              'dose': 100,   'unit': 'mg'},

    # ── PSYCHEDELICS ──────────────────────────────────────────────────────────
    {'names': ['psilocybin', 'psilocin'],          'dose': 25,    'unit': 'mg'},
    {'names': ['lysergic acid diethylamide', 'lsd'],'dose': 100,  'unit': 'mcg'},
    {'names': ['dimethyltryptamine',
               '5-meo-dmt', '5-methoxy-dmt'],      'dose': 20,    'unit': 'mg'},
    {'names': ['mescaline'],                       'dose': 200,   'unit': 'mg'},
    {'names': ['ibogaine', 'noribogaine'],         'dose': 15,    'unit': 'mg'},

    # ── EMPATHOGENS ───────────────────────────────────────────────────────────
    {'names': ['3,4-methylenedioxymethamphetamine',
               'mdma'],                            'dose': 80,    'unit': 'mg'},
    {'names': ['3,4-methylenedioxyamphetamine',
               'mda'],                             'dose': 80,    'unit': 'mg'},

    # ── DISSOCIATIVES ─────────────────────────────────────────────────────────
    {'names': ['esketamine'],                      'dose': 56,    'unit': 'mg'},
    {'names': ['ketamine'],                        'dose': 35,    'unit': 'mg'},
    {'names': ['memantine'],                       'dose': 10,    'unit': 'mg'},
    {'names': ['dextromethorphan'],                'dose': 30,    'unit': 'mg'},
    {'names': ['phencyclidine', 'pcp'],            'dose': 5,     'unit': 'mg'},

    # ── STIMULANTS ────────────────────────────────────────────────────────────
    {'names': ['caffeine'],                        'dose': 200,   'unit': 'mg'},
    {'names': ['theobromine'],                     'dose': 100,   'unit': 'mg'},
    {'names': ['theacrine'],                       'dose': 100,   'unit': 'mg'},
    {'names': ['clenbuterol'],                     'dose': 20,    'unit': 'mcg'},
    {'names': ['ephedrine'],                       'dose': 25,    'unit': 'mg'},
    {'names': ['pseudoephedrine'],                 'dose': 60,    'unit': 'mg'},
    {'names': ['yohimbine', 'alpha-yohimbine',
               'beta-yohimbine'],                  'dose': 5,     'unit': 'mg'},
    {'names': ['amphetamine'],                     'dose': 10,    'unit': 'mg'},
    {'names': ['methamphetamine'],                 'dose': 5,     'unit': 'mg'},
    {'names': ['methylphenidate'],                 'dose': 10,    'unit': 'mg'},
    {'names': ['cocaine'],                         'dose': 100,   'unit': 'mg'},

    # ── OPIOIDS ───────────────────────────────────────────────────────────────
    {'names': ['morphine'],                        'dose': 10,    'unit': 'mg'},
    {'names': ['oxycodone'],                       'dose': 10,    'unit': 'mg'},
    {'names': ['hydrocodone'],                     'dose': 5,     'unit': 'mg'},
    {'names': ['fentanyl'],                        'dose': 25,    'unit': 'mcg'},
    {'names': ['tramadol'],                        'dose': 100,   'unit': 'mg'},
    {'names': ['buprenorphine'],                   'dose': 8,     'unit': 'mg'},
    {'names': ['naltrexone'],                      'dose': 50,    'unit': 'mg'},
    {'names': ['methadone'],                       'dose': 80,    'unit': 'mg'},
    {'names': ['codeine'],                         'dose': 30,    'unit': 'mg'},

    # ── DOPAMINERGIC ──────────────────────────────────────────────────────────
    {'names': ['levodopa', 'l-dopa'],              'dose': 100,   'unit': 'mg'},
    {'names': ['pramipexole'],                     'dose': 0.5,   'unit': 'mg'},
    {'names': ['ropinirole'],                      'dose': 1,     'unit': 'mg'},
    {'names': ['apomorphine'],                     'dose': 4,     'unit': 'mg'},
    {'names': ['selegiline'],                      'dose': 5,     'unit': 'mg'},
    {'names': ['rasagiline'],                      'dose': 1,     'unit': 'mg'},

    # ── SEROTONERGIC / ANTIDEPRESSANTS ────────────────────────────────────────
    {'names': ['fluoxetine'],                      'dose': 20,    'unit': 'mg'},
    {'names': ['sertraline'],                      'dose': 50,    'unit': 'mg'},
    {'names': ['paroxetine'],                      'dose': 20,    'unit': 'mg'},
    {'names': ['escitalopram'],                    'dose': 10,    'unit': 'mg'},
    {'names': ['citalopram'],                      'dose': 20,    'unit': 'mg'},
    {'names': ['venlafaxine'],                     'dose': 75,    'unit': 'mg'},
    {'names': ['duloxetine'],                      'dose': 60,    'unit': 'mg'},
    {'names': ['mirtazapine'],                     'dose': 15,    'unit': 'mg'},
    {'names': ['bupropion'],                       'dose': 150,   'unit': 'mg'},
    {'names': ['phenelzine'],                      'dose': 15,    'unit': 'mg'},
    {'names': ['tranylcypromine'],                 'dose': 10,    'unit': 'mg'},

    # ── GABAergic / BENZODIAZEPINES / BARBITURATES ────────────────────────────
    {'names': ['diazepam'],                        'dose': 5,     'unit': 'mg'},
    {'names': ['lorazepam'],                       'dose': 2,     'unit': 'mg'},
    {'names': ['alprazolam'],                      'dose': 0.5,   'unit': 'mg'},
    {'names': ['clonazepam'],                      'dose': 0.5,   'unit': 'mg'},
    {'names': ['midazolam'],                       'dose': 5,     'unit': 'mg'},
    {'names': ['nitrazepam'],                      'dose': 5,     'unit': 'mg'},
    {'names': ['triazolam'],                       'dose': 0.25,  'unit': 'mg'},
    {'names': ['temazepam'],                       'dose': 15,    'unit': 'mg'},
    {'names': ['oxazepam'],                        'dose': 15,    'unit': 'mg'},
    {'names': ['clobazam'],                        'dose': 10,    'unit': 'mg'},
    {'names': ['baclofen'],                        'dose': 10,    'unit': 'mg'},
    {'names': ['phenobarbital'],                   'dose': 30,    'unit': 'mg'},
    {'names': ['pentobarbital'],                   'dose': 50,    'unit': 'mg'},
    {'names': ['amobarbital'],                     'dose': 65,    'unit': 'mg'},
    {'names': ['barbital'],                        'dose': 300,   'unit': 'mg'},

    # ── CHOLINERGICS ──────────────────────────────────────────────────────────
    {'names': ['galantamine'],                     'dose': 8,     'unit': 'mg'},
    {'names': ['donepezil'],                       'dose': 5,     'unit': 'mg'},
    {'names': ['rivastigmine'],                    'dose': 3,     'unit': 'mg'},

    # ── LONGEVITY / NAD+ / mTOR ───────────────────────────────────────────────
    {'names': ['rapamycin', 'sirolimus'],          'dose': 5,     'unit': 'mg'},
    {'names': ['everolimus'],                      'dose': 10,    'unit': 'mg'},
    {'names': ['metformin'],                       'dose': 500,   'unit': 'mg'},
    {'names': ['nicotinamide riboside',
               'nr '],                             'dose': 300,   'unit': 'mg'},
    {'names': ['nicotinamide mononucleotide',
               'nmn'],                             'dose': 300,   'unit': 'mg'},
    {'names': ['resveratrol'],                     'dose': 150,   'unit': 'mg'},
    {'names': ['pterostilbene'],                   'dose': 50,    'unit': 'mg'},
    {'names': ['berberine'],                       'dose': 500,   'unit': 'mg'},
    {'names': ['quercetin'],                       'dose': 500,   'unit': 'mg'},
    {'names': ['curcumin'],                        'dose': 500,   'unit': 'mg'},
    {'names': ['fisetin'],                         'dose': 100,   'unit': 'mg'},
    {'names': ['spermidine'],                      'dose': 1,     'unit': 'mg'},
    {'names': ['coenzyme q10', 'ubiquinone',
               'ubiquinol', 'coq10'],              'dose': 100,   'unit': 'mg'},
    {'names': ['lipoic acid', 'alpha-lipoic acid'],'dose': 300,   'unit': 'mg'},
    {'names': ['n-acetylcysteine', 'nac'],         'dose': 600,   'unit': 'mg'},

    # ── METABOLIC / GLP-1 / THYROID ───────────────────────────────────────────
    {'names': ['semaglutide'],                     'dose': 1,     'unit': 'mg'},
    {'names': ['liraglutide'],                     'dose': 1.2,   'unit': 'mg'},
    {'names': ['tirzepatide'],                     'dose': 5,     'unit': 'mg'},
    {'names': ['liothyronine'],                    'dose': 25,    'unit': 'mcg'},
    {'names': ['levothyroxine'],                   'dose': 50,    'unit': 'mcg'},

    # ── CARDIOVASCULAR / LIPID ────────────────────────────────────────────────
    {'names': ['sildenafil'],                      'dose': 50,    'unit': 'mg'},
    {'names': ['tadalafil'],                       'dose': 10,    'unit': 'mg'},
    {'names': ['vardenafil'],                      'dose': 10,    'unit': 'mg'},
    {'names': ['atorvastatin'],                    'dose': 20,    'unit': 'mg'},
    {'names': ['rosuvastatin'],                    'dose': 10,    'unit': 'mg'},
    {'names': ['simvastatin'],                     'dose': 20,    'unit': 'mg'},
    {'names': ['lovastatin'],                      'dose': 20,    'unit': 'mg'},
    {'names': ['pravastatin'],                     'dose': 20,    'unit': 'mg'},
    {'names': ['aspirin', 'acetylsalicylic acid'], 'dose': 81,    'unit': 'mg'},
    {'names': ['ibuprofen'],                       'dose': 400,   'unit': 'mg'},
    {'names': ['celecoxib'],                       'dose': 200,   'unit': 'mg'},

    # ── ANTIPSYCHOTICS ────────────────────────────────────────────────────────
    {'names': ['haloperidol'],                     'dose': 5,     'unit': 'mg'},
    {'names': ['risperidone'],                     'dose': 2,     'unit': 'mg'},
    {'names': ['olanzapine'],                      'dose': 10,    'unit': 'mg'},
    {'names': ['quetiapine'],                      'dose': 300,   'unit': 'mg'},
    {'names': ['aripiprazole'],                    'dose': 15,    'unit': 'mg'},
    {'names': ['clozapine'],                       'dose': 300,   'unit': 'mg'},

    # ── ANTIHISTAMINES ────────────────────────────────────────────────────────
    {'names': ['diphenhydramine'],                 'dose': 25,    'unit': 'mg'},
    {'names': ['cetirizine'],                      'dose': 10,    'unit': 'mg'},
    {'names': ['loratadine'],                      'dose': 10,    'unit': 'mg'},
    {'names': ['fexofenadine'],                    'dose': 180,   'unit': 'mg'},

    # ── IMMUNOSUPPRESSANTS ────────────────────────────────────────────────────
    {'names': ['cyclosporine'],                    'dose': 200,   'unit': 'mg'},
    {'names': ['tacrolimus'],                      'dose': 5,     'unit': 'mg'},
    {'names': ['mycophenolate'],                   'dose': 1000,  'unit': 'mg'},
]


def _apply_profile(profile: dict, dry_run: bool, overwrite: bool, stdout) -> tuple[int, int]:
    """Apply one dose profile. Returns (set, skipped) counts."""
    set_count = skipped = 0
    for name_frag in profile['names']:
        qs = Compound.objects.filter(name__icontains=name_frag)
        for compound in qs:
            if not overwrite and compound.standard_dose is not None:
                skipped += 1
                continue
            if dry_run:
                stdout.write(
                    f'  [dry] {compound.name}: '
                    f'{profile["dose"]} {profile["unit"]}'
                )
                continue
            compound.standard_dose = profile['dose']
            compound.standard_dose_unit = profile['unit']
            compound.save(update_fields=['standard_dose', 'standard_dose_unit'])
            set_count += 1
    return set_count, skipped


class Command(BaseCommand):
    help = 'Seed Compound.standard_dose for key builder compounds from literature.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print matches without writing to DB.',
        )
        parser.add_argument(
            '--overwrite', action='store_true',
            help='Overwrite existing standard_dose values (default: skip them).',
        )

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
                    f'Done.  Set: {total_set}  Skipped (already had value): {total_skipped}'
                )
            )
