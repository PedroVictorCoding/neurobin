"""
Management command: populate_compound_safety
--------------------------------------------
Seeds CompoundSafetyScreening records for all key compounds in the stack builder
using published pharmacological literature.

Scale (all fields): 1 = none / minimal  …  5 = lethal / full
  liver_toxicity    : hepatic injury potential
  hpta_suppression  : gonadal axis suppression
  cardiovascular_risk: cardiac / vascular risk
  kidney_toxicity   : renal injury potential
  neurotoxicity     : CNS toxicity potential

Usage:
  python manage.py populate_compound_safety
  python manage.py populate_compound_safety --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from compounds.models import Compound, CompoundSafetyScreening

# ---------------------------------------------------------------------------
# Safety profiles
# Each entry:
#   'names'  – list of lowercase substrings; a compound matches if its name
#               contains ANY of these substrings (case-insensitive)
#   liver / hpta / cardio / kidney / neuro  – 1–5 safety scores
# ---------------------------------------------------------------------------
PROFILES: list[dict] = [

    # ── ANDROGENS / AAS – INJECTABLE (low liver, full HPTA suppression) ──────
    {
        'names': [
            'testosterone',   # catches base form + all esters via icontains
            'sustanon',
        ],
        'liver': 1, 'hpta': 5, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['nandrolone decanoate', 'nandrolone phenylpropionate', 'nandrolone undecanoate'],
        'liver': 1, 'hpta': 5, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['boldenone undecylenate', 'boldenone cypionate'],
        'liver': 1, 'hpta': 5, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': [
            'trenbolone',   # catches base form + all esters via icontains
        ],
        'liver': 2, 'hpta': 5, 'cardio': 4, 'kidney': 2, 'neuro': 2,
    },
    {
        'names': ['drostanolone propionate', 'drostanolone enanthate'],
        'liver': 1, 'hpta': 5, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['methenolone enanthate', 'methenolone acetate'],
        'liver': 1, 'hpta': 4, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['trestolone acetate', 'trestolone enanthate', 'ment '],
        'liver': 2, 'hpta': 5, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['clostebol acetate', 'clostebol propionate'],
        'liver': 2, 'hpta': 4, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['epitestosterone'],
        'liver': 1, 'hpta': 2, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── ANDROGENS / AAS – ORAL 17α-ALKYLATED (high liver, full HPTA) ─────────
    {
        'names': ['stanozolol'],
        'liver': 4, 'hpta': 5, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['oxandrolone'],
        'liver': 3, 'hpta': 4, 'cardio': 2, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['methandrostenolone', 'methandienone'],
        'liver': 5, 'hpta': 5, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['oxymetholone'],
        'liver': 5, 'hpta': 5, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['fluoxymesterone'],
        'liver': 5, 'hpta': 5, 'cardio': 4, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['methyltestosterone'],
        'liver': 4, 'hpta': 5, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['mesterolone'],
        'liver': 2, 'hpta': 2, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['methasterone', 'superdrol'],
        'liver': 5, 'hpta': 5, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['dimethyltrienolone'],
        'liver': 5, 'hpta': 5, 'cardio': 4, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['gestrinone'],
        'liver': 3, 'hpta': 4, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── SARMs ─────────────────────────────────────────────────────────────────
    {
        'names': ['ostarine', 'mk-2866', 'enobosarm'],
        'liver': 2, 'hpta': 2, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ligandrol', 'lgd-4033', 'lgd4033', 'vk5211'],
        'liver': 2, 'hpta': 4, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['rad-140', 'rad140', 'testolone'],
        'liver': 3, 'hpta': 4, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['andarine', 's-4 ', 's4 '],
        'liver': 2, 'hpta': 3, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['yk11'],
        'liver': 3, 'hpta': 4, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['s23'],
        'liver': 3, 'hpta': 5, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ac-262', 'ac262'],
        'liver': 2, 'hpta': 3, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['gsk2881078'],
        'liver': 2, 'hpta': 3, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── PPAR / METABOLIC MODULATORS ───────────────────────────────────────────
    {
        'names': ['cardarine', 'gw501516', 'gw-501516'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['sr9009', 'stenabolic'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ibutamoren', 'mk-677', 'mk677'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── GH AXIS / SECRETAGOGUES ───────────────────────────────────────────────
    {
        'names': ['ipamorelin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['sermorelin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['cjc-1295', 'cjc1295'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['hexarelin'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ghrp-2', 'ghrp2'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ghrp-6', 'ghrp6'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['tesamorelin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['somatropin', 'somatotropin', 'human growth hormone'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['mecasermin', 'igf-1', 'insulin-like growth factor'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['aod-9604', 'aod9604'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── REPAIR / TISSUE PEPTIDES ──────────────────────────────────────────────
    {
        'names': ['bpc-157', 'bpc157'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['tb-500', 'tb500', 'thymosin beta'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ghk-cu', 'ghk copper', 'copper peptide'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['mechano growth factor', 'mgf'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── ESTROGEN MODULATORS (AIs / SERMs) ─────────────────────────────────────
    {
        'names': ['anastrozole'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['letrozole'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['exemestane'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['tamoxifen'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['clomiphene', 'clomid'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['enclomiphene'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['raloxifene'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['fulvestrant'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['toremifene'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['4-hydroxytamoxifen', '4-ohta'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── ANCILLARIES (prolactin / hCG) ─────────────────────────────────────────
    {
        'names': ['cabergoline'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['bromocriptine'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['chorionic gonadotropin', 'hcg'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── NOOTROPICS / RACETAMS ─────────────────────────────────────────────────
    {
        'names': ['piracetam'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['aniracetam'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['oxiracetam'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['pramiracetam'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['phenylpiracetam'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['noopept', 'n-phenylacetyl-l-prolylglycine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['modafinil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['armodafinil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['vinpocetine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['huperzine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['citicoline', 'cdp-choline'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['alpha-gpc', 'alpha gpc'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['semax'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['selank'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['cerebrolysin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['epitalon', 'epithalon'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── SLEEP / CIRCADIAN ─────────────────────────────────────────────────────
    {
        'names': ['melatonin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ramelteon'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['agomelatine'],
        'liver': 3, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['phenibut'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['zolpidem'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['eszopiclone'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['zaleplon'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['suvorexant'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['lemborexant'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['daridorexant'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['sodium oxybate', 'gamma-hydroxybutyrate', 'ghb'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 3,
    },

    # ── ADAPTOGENS ────────────────────────────────────────────────────────────
    {
        'names': ['ashwagandha', 'withania somnifera', 'withanolide'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['rhodiola'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['panax ginseng', 'panax quinquefolius', 'ginsenoside'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['l-theanine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['phosphatidylserine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── PSYCHEDELICS ──────────────────────────────────────────────────────────
    {
        'names': ['psilocybin', 'psilocin'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['lysergic acid diethylamide', 'lsd'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['dimethyltryptamine', '5-meo-dmt', '5-methoxy-dmt'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['mescaline'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ibogaine', 'noribogaine'],
        'liver': 2, 'hpta': 1, 'cardio': 4, 'kidney': 1, 'neuro': 2,
    },

    # ── EMPATHOGENS ───────────────────────────────────────────────────────────
    {
        'names': ['3,4-methylenedioxymethamphetamine', 'mdma'],
        'liver': 3, 'hpta': 1, 'cardio': 4, 'kidney': 1, 'neuro': 3,
    },
    {
        'names': ['3,4-methylenedioxyamphetamine', 'mda'],
        'liver': 3, 'hpta': 1, 'cardio': 4, 'kidney': 1, 'neuro': 3,
    },

    # ── DISSOCIATIVES ─────────────────────────────────────────────────────────
    {
        'names': ['ketamine'],
        'liver': 3, 'hpta': 1, 'cardio': 2, 'kidney': 3, 'neuro': 2,
    },
    {
        'names': ['esketamine'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 2, 'neuro': 2,
    },
    {
        'names': ['memantine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['dextromethorphan'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['phencyclidine', 'pcp'],
        'liver': 2, 'hpta': 1, 'cardio': 3, 'kidney': 2, 'neuro': 4,
    },

    # ── STIMULANTS ────────────────────────────────────────────────────────────
    {
        'names': ['caffeine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['theobromine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['theacrine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['clenbuterol'],
        'liver': 1, 'hpta': 1, 'cardio': 4, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ephedrine'],
        'liver': 2, 'hpta': 1, 'cardio': 4, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['pseudoephedrine'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['yohimbine', 'alpha-yohimbine', 'beta-yohimbine'],
        'liver': 2, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['amphetamine'],
        'liver': 2, 'hpta': 1, 'cardio': 4, 'kidney': 2, 'neuro': 3,
    },
    {
        'names': ['methamphetamine'],
        'liver': 2, 'hpta': 1, 'cardio': 4, 'kidney': 2, 'neuro': 4,
    },
    {
        'names': ['methylphenidate'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['cocaine'],
        'liver': 3, 'hpta': 1, 'cardio': 5, 'kidney': 2, 'neuro': 3,
    },

    # ── OPIOIDS ───────────────────────────────────────────────────────────────
    {
        'names': ['morphine'],
        'liver': 2, 'hpta': 3, 'cardio': 2, 'kidney': 2, 'neuro': 2,
    },
    {
        'names': ['oxycodone'],
        'liver': 2, 'hpta': 3, 'cardio': 2, 'kidney': 2, 'neuro': 2,
    },
    {
        'names': ['hydrocodone'],
        'liver': 2, 'hpta': 3, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['fentanyl'],
        'liver': 2, 'hpta': 3, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['tramadol'],
        'liver': 2, 'hpta': 2, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['buprenorphine'],
        'liver': 3, 'hpta': 2, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['naltrexone'],
        'liver': 3, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['methadone'],
        'liver': 2, 'hpta': 3, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['codeine'],
        'liver': 2, 'hpta': 2, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── DOPAMINERGIC ─────────────────────────────────────────────────────────
    {
        'names': ['levodopa', 'l-dopa'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['pramipexole'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['ropinirole'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['apomorphine'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['selegiline'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['rasagiline'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── SEROTONERGIC / ANTIDEPRESSANTS ────────────────────────────────────────
    {
        'names': ['fluoxetine'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['sertraline'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['paroxetine'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['escitalopram'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['citalopram'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['venlafaxine'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['duloxetine'],
        'liver': 3, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['mirtazapine'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['bupropion'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['phenelzine', 'tranylcypromine'],
        'liver': 3, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },

    # ── GABAergic / BENZODIAZEPINES / BARBITURATES ────────────────────────────
    {
        'names': [
            'diazepam', 'lorazepam', 'alprazolam', 'clonazepam',
            'midazolam', 'nitrazepam', 'triazolam', 'temazepam',
            'oxazepam', 'clobazam', 'clonazepam',
        ],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['baclofen'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['phenobarbital', 'barbital', 'amobarbital', 'pentobarbital'],
        'liver': 3, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 3,
    },

    # ── CHOLINERGICS ──────────────────────────────────────────────────────────
    {
        'names': ['galantamine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['donepezil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['rivastigmine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── LONGEVITY / NAD+ / mTOR ───────────────────────────────────────────────
    {
        'names': ['rapamycin', 'sirolimus'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['everolimus'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['metformin'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['nicotinamide riboside', 'nicotinamide mononucleotide', 'nmn', 'nr '],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['resveratrol'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['pterostilbene'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['berberine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['quercetin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['curcumin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['fisetin'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['spermidine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['coenzyme q10', 'ubiquinone', 'ubiquinol', 'coq10'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['lipoic acid', 'alpha-lipoic acid'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['n-acetylcysteine', 'nac'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── METABOLIC / GLP-1 / THYROID ───────────────────────────────────────────
    {
        'names': ['semaglutide'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['liraglutide'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['tirzepatide'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['liothyronine'],
        'liver': 1, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['levothyroxine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },

    # ── CARDIOVASCULAR / LIPID ────────────────────────────────────────────────
    {
        'names': ['sildenafil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['tadalafil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['vardenafil'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['atorvastatin', 'rosuvastatin', 'simvastatin', 'lovastatin', 'pravastatin'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['aspirin', 'acetylsalicylic acid'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['ibuprofen'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 2, 'neuro': 1,
    },
    {
        'names': ['celecoxib'],
        'liver': 2, 'hpta': 1, 'cardio': 3, 'kidney': 2, 'neuro': 1,
    },

    # ── ANTIPSYCHOTICS ────────────────────────────────────────────────────────
    {
        'names': ['haloperidol'],
        'liver': 2, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['risperidone'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['olanzapine'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['quetiapine'],
        'liver': 2, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['aripiprazole'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },
    {
        'names': ['clozapine'],
        'liver': 2, 'hpta': 1, 'cardio': 3, 'kidney': 1, 'neuro': 2,
    },

    # ── ANTIHISTAMINES ────────────────────────────────────────────────────────
    {
        'names': ['diphenhydramine'],
        'liver': 1, 'hpta': 1, 'cardio': 2, 'kidney': 1, 'neuro': 2,
    },
    {
        'names': ['cetirizine', 'loratadine', 'fexofenadine'],
        'liver': 1, 'hpta': 1, 'cardio': 1, 'kidney': 1, 'neuro': 1,
    },

    # ── IMMUNOSUPPRESSANTS ────────────────────────────────────────────────────
    {
        'names': ['cyclosporine', 'tacrolimus'],
        'liver': 3, 'hpta': 1, 'cardio': 2, 'kidney': 4, 'neuro': 2,
    },
    {
        'names': ['mycophenolate'],
        'liver': 2, 'hpta': 1, 'cardio': 1, 'kidney': 2, 'neuro': 1,
    },
]


def _apply_profile(
    profile: dict,
    dry_run: bool,
    stdout,
) -> tuple[int, int]:
    """Apply one safety profile. Returns (created, updated) counts."""
    created = updated = 0
    for name_frag in profile['names']:
        qs = Compound.objects.filter(name__icontains=name_frag)
        for compound in qs:
            if dry_run:
                stdout.write(f'  [dry] {compound.name}')
                continue
            obj, was_created = CompoundSafetyScreening.objects.get_or_create(
                compound=compound,
                defaults={
                    'liver_toxicity':     profile['liver'],
                    'hpta_suppression':   profile['hpta'],
                    'cardiovascular_risk': profile['cardio'],
                    'kidney_toxicity':    profile['kidney'],
                    'neurotoxicity':      profile['neuro'],
                    'confidence_score':   3,
                },
            )
            if was_created:
                created += 1
            else:
                # Only overwrite if all values are null (don't clobber manual edits)
                if all(
                    getattr(obj, f) is None
                    for f in ('liver_toxicity', 'hpta_suppression',
                              'cardiovascular_risk', 'kidney_toxicity', 'neurotoxicity')
                ):
                    obj.liver_toxicity      = profile['liver']
                    obj.hpta_suppression    = profile['hpta']
                    obj.cardiovascular_risk = profile['cardio']
                    obj.kidney_toxicity     = profile['kidney']
                    obj.neurotoxicity       = profile['neuro']
                    obj.confidence_score    = 3
                    obj.save()
                    updated += 1
    return created, updated


class Command(BaseCommand):
    help = 'Seed CompoundSafetyScreening records for key builder compounds.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print matched compounds without writing to DB.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_created = total_updated = 0

        with transaction.atomic():
            for profile in PROFILES:
                c, u = _apply_profile(profile, dry_run, self.stdout)
                total_created += c
                total_updated += u

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes written.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Done. Created: {total_created}  Updated (null→value): {total_updated}'
                )
            )
