"""
Management command: populate_builder_tags
=========================================
Populates two tables:
  1. CompoundSteroidRating  – anabolic/androgenic ratings for known AAS
  2. CompoundTaxonomyTag    – which builder taxonomy sub a compound belongs to

Usage:
    python manage.py populate_builder_tags
    python manage.py populate_builder_tags --clear   # wipe & redo taxonomy
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from compounds.models import Compound, CompoundSteroidRating
from stacks.models import CompoundTaxonomyTag


# ── Known AAS steroid ratings (relative to testosterone = 100) ────────────────
# Source: clinical pharmacology / standard reference tables
# (anabolic_rating, androgenic_rating)
STEROID_RATINGS = {
    # Testosterone esters – all share the same base rating
    'TESTOSTERONE PROPIONATE':           (100, 100),
    'TESTOSTERONE ENANTHATE':            (100, 100),
    'TESTOSTERONE CYPIONATE':            (100, 100),
    'TESTOSTERONE UNDECANOATE':          (100, 100),
    'TESTOSTERONE':                      (100, 100),
    # 19-nor androgens
    'NANDROLONE DECANOATE':              (125,  37),
    'NANDROLONE PHENYLPROPIONATE':       (125,  37),
    'NANDROLONE':                        (125,  37),
    'TRENBOLONE ACETATE':                (500, 500),
    'TRENBOLONE ENANTHATE':              (500, 500),
    'TRENBOLONE':                        (500, 500),
    # DHT-derived
    'STANOZOLOL':                        (320,  30),
    'OXANDROLONE':                       (400,  24),
    'OXYMETHOLONE':                      (320,  45),
    'DROSTANOLONE PROPIONATE':           ( 62,  25),
    'DROSTANOLONE ENANTHATE':            ( 62,  25),
    'DROSTANOLONE':                      ( 62,  25),
    'METHENOLONE ENANTHATE':             ( 88,  44),
    'METHENOLONE ACETATE':               ( 88,  44),
    'METHENOLONE':                       ( 88,  44),
    'FLUOXYMESTERONE':                   (1900, 850),
    'MESTEROLONE':                       ( 40,  30),
    'CLOSTEBOL':                         ( 25,   7),
    # Alkylated / mixed
    'METHANDROSTENOLONE':                (210,  60),
    'METHYLTESTOSTERONE':                (115, 115),
    'BOLDENONE UNDECYLENATE':            (100,  50),
    'BOLDENONE':                         (100,  50),
    'EPITESTOSTERONE':                   ( 10,  10),
    # Newer / research
    'TRESTOLONE ACETATE':                (2300, 650),
    'TRESTOLONE':                        (2300, 650),
}


# ── Taxonomy helpers ──────────────────────────────────────────────────────────

def moaHas(moa_list, *kws):
    t = ' '.join(moa_list).lower()
    return any(k.lower() in t for k in kws)

def catHas(cats, *kws):
    t = ' '.join(cats).lower()
    return any(k.lower() in t for k in kws)

def nameIs(name, aka, *kws):
    t = (name + ' ' + aka).lower()
    return any(k.lower() in t for k in kws)


# ── Full taxonomy (mirrors stack_builder.html JS) ─────────────────────────────
# Each entry: (group_id, group_label, sub_id, sub_label, match_fn)
# match_fn(moa_list, cats_list, name_str, aka_str) -> bool

def _taxonomy():
    return [
        ('anabolism', 'Anabolism & Performance', [
            ('androgens', 'Androgens / AAS', lambda m, c, n, a:
                moaHas(m, 'androgen receptor', 'ar agonist')
                or catHas(c, 'anabolic agent', 'anabolic steroid', 'sex hormone', 'androgenic')
                or nameIs(n, a, 'testosterone', 'nandrolone', 'trenbolone', 'boldenone',
                            'stanozolol', 'oxandrolone', 'methandrostenolone', 'oxymetholone',
                            'drostanolone', 'methenolone', 'fluoxymesterone', 'halotestin',
                            'trestolone', 'ment', 'mesterolone', 'clostebol', 'methyltestosterone',
                            'superdrol', 'methasterone', 'dimethyltrienolone', 'epitestosterone',
                            'primobolan', 'winstrol', 'dianabol', 'anadrol', 'masteron', 'proviron')
            ),
            ('sarms', 'SARMs', lambda m, c, n, a:
                moaHas(m, 'selective androgen')
                or catHas(c, 'sarm')
                or nameIs(n, a, 'ostarine', 'mk-2866', 'ligandrol', 'lgd4033', 'lgd-4033',
                            'lgd 4033', 'rad-140', 'rad140', 'andarine', 's4 ', 'yk11',
                            's23', 'ac-262', 'enobosarm', 'gsk2881078')
            ),
            ('estrogen_mod', 'Estrogen Modulators (AI / SERM)', lambda m, c, n, a:
                moaHas(m, 'estrogen receptor', 'aromatase', 'cytochrome p450 19',
                          'cytochrome p450 11')
                or catHas(c, 'endocrine therapy', 'breast carcinoma', 'sex hormone')
                or nameIs(n, a, 'anastrozole', 'letrozole', 'exemestane', 'tamoxifen',
                            'clomiphene', 'raloxifene', 'fulvestrant', 'toremifene',
                            'enclomiphene', 'arimidex', 'aromasin', 'nolvadex', 'clomid',
                            '4-hydroxytamoxifen', 'hydroxyclomiphene', 'desmethyl tamoxifen')
            ),
            ('gh_axis', 'Growth Hormone Axis', lambda m, c, n, a:
                moaHas(m, 'growth hormone', 'ghrelin', 'igf-1', 'gh receptor',
                          'growth hormone receptor', 'ghrh')
                or nameIs(n, a, 'ipamorelin', 'sermorelin', 'hexarelin', 'ghrp-2', 'ghrp-6',
                            'ghrp2', 'ghrp6', 'cjc-1295', 'cjc1295', 'tesamorelin',
                            'ibutamoren', 'mk677', 'mk-677', 'igf-1', 'igf1',
                            'aod-9604', 'aod9604', 'hgh', 'somatropin', 'mecasermin')
            ),
            ('peptides_repair', 'Peptides (Repair & Tissue)', lambda m, c, n, a:
                nameIs(n, a, 'bpc-157', 'bpc157', 'tb-500', 'tb500', 'thymosin',
                         'ghk-cu', 'ghk copper', 'mechano growth', 'mgf')
            ),
            ('sarms_ppar', 'Metabolic Modulators (PPAR / AMPK)', lambda m, c, n, a:
                moaHas(m, 'ppar', 'peroxisome proliferator')
                or catHas(c, 'ppar')
                or nameIs(n, a, 'cardarine', 'gw501516', 'gw-501516', 'sr9009', 'stenabolic',
                            'ibutamoren', 'mk677')
            ),
            ('ancillaries', 'Ancillaries (hCG / Prolactin / Liver)', lambda m, c, n, a:
                moaHas(m, 'gonadotropin', 'prolactin', 'follicle stimulating',
                          'lh receptor', 'fsh receptor', 'lutenizing')
                or catHas(c, 'anti-parkinson', 'antiparkinsonian', 'gonadotropin', 'prolactin')
                or nameIs(n, a, 'cabergoline', 'bromocriptine', 'hcg', 'chorionic gonadotropin',
                            'p5p', 'pyridoxal')
            ),
        ]),
        ('cognition', 'Cognition & Neuroscience', [
            ('dopaminergic', 'Dopaminergic', lambda m, c, n, a:
                moaHas(m, 'dopamine', 'd(1) dopamine', 'd(2) dopamine', 'd(3) dopamine',
                          'd(4) dopamine', 'dopamine transporter', 'mao-b')
                or catHas(c, 'anti-parkinson', 'antiparkinsonian', 'antipsychotic',
                            'antipsychotics', 'dopamine', 'psychosis treatment')
            ),
            ('serotonergic', 'Serotonergic', lambda m, c, n, a:
                moaHas(m, 'serotonin', '5-ht', 'sert', 'serotonin transporter',
                          'serotonin receptor', '5ht')
                or catHas(c, 'antidepressant', 'anxiolytic', 'ssri', 'snri', 'serotonin')
            ),
            ('gabaergic', 'GABAergic', lambda m, c, n, a:
                moaHas(m, 'gaba', 'gaba-a', 'gaba-b', 'gabaa', 'gabab',
                          'benzodiazepine', 'anion channel')
                or catHas(c, 'anxiolytic', 'anxiolytics', 'benzodiazepine', 'barbiturate',
                            'hypnotics', 'sedative', 'gaba')
            ),
            ('glutamatergic', 'Glutamatergic (AMPA / NMDA / mGluR)', lambda m, c, n, a:
                moaHas(m, 'glutamate', 'ampa', 'nmda', 'kainate', 'mglur',
                          'metabotropic glutamate', 'glutamate receptor ionotropic',
                          'glutamate [nmda]')
                or nameIs(n, a, 'ketamine', 'esketamine', 'memantine', 'nmda', 'ampa',
                            'dxm', 'dextromethorphan', 'mxe')
            ),
            ('cholinergic', 'Cholinergic (AChE / Muscarinic / Nicotinic)', lambda m, c, n, a:
                moaHas(m, 'acetylcholin', 'muscarinic', 'nicotinic', 'cholinesterase',
                          'acetylcholinesterase')
                or catHas(c, 'cholinergic', 'parasympathomimetic', 'acetylcholinesterase')
                or nameIs(n, a, 'huperzine', 'alpha-gpc', 'cdp-choline', 'citicoline',
                            'acetylcholine', 'galantamine', 'donepezil', 'rivastigmine')
            ),
            ('nootropics_gen', 'Nootropics & Cognitive Enhancers', lambda m, c, n, a:
                catHas(c, 'nootropic', 'neuroenhancer', 'cognitive enhancer', 'cognition',
                         'adhd treatment', 'dementia', 'psychostimulant')
                or nameIs(n, a, 'piracetam', 'aniracetam', 'oxiracetam', 'pramiracetam',
                            'noopept', 'phenylpiracetam', 'modafinil', 'armodafinil',
                            'vinpocetine', 'semax', 'selank', 'cerebrolysin', 'epitalon',
                            'epithalon', 'dsip', 'thymalin')
            ),
            ('noradrenergic', 'Noradrenergic / NE Reuptake', lambda m, c, n, a:
                moaHas(m, 'norepinephrine transporter', 'norepinephrine', 'noradrenalin')
                or catHas(c, 'snri', 'norepinephrine reuptake')
            ),
            ('adrenergic', 'Adrenergic (α / β)', lambda m, c, n, a:
                moaHas(m, 'adrenergic receptor', 'alpha-1', 'alpha-2', 'beta-1 adrenergic',
                          'beta-2 adrenergic', 'beta-3 adrenergic', 'adrenoceptor',
                          'adrenergic receptor alpha')
                or catHas(c, 'adrenergic', 'beta blocker', 'beta blockers', 'alpha blocker',
                            'adrenergics')
            ),
            ('sigma_r', 'Sigma Receptors', lambda m, c, n, a:
                moaHas(m, 'sigma', 'sigma-1', 'sigma-2', 'sigma non-opioid',
                          'sigma 1', 'sigma 2')
            ),
            ('histaminergic', 'Histaminergic', lambda m, c, n, a:
                moaHas(m, 'histamine', 'h1 receptor', 'h2 receptor', 'h3 receptor',
                          'histamine receptor', 'histamine h')
                or catHas(c, 'antihistamine', 'antihistamines', 'h1 antagonist', 'h2 antagonist')
            ),
            ('opioidergic', 'Opioidergic', lambda m, c, n, a:
                moaHas(m, 'opioid', 'mu-type opioid', 'delta opioid', 'kappa opioid',
                          'mu receptor', 'opioid receptor', 'delta-type opioid')
                or catHas(c, 'opioid', 'narcotic', 'opioid dependence', 'analgesic')
            ),
            ('adenosinergic', 'Adenosinergic / Xanthines', lambda m, c, n, a:
                moaHas(m, 'adenosine receptor', 'adenosine a1', 'adenosine a2', 'adenosine a3')
                or catHas(c, 'adenosine')
                or nameIs(n, a, 'caffeine', 'theobromine', 'theacrine', 'dpcpx')
            ),
            ('cannabinoid', 'Cannabinoids', lambda m, c, n, a:
                moaHas(m, 'cannabinoid', 'cb1', 'cb2', 'cannabis', 'endocannabinoid')
                or catHas(c, 'cannabinoid')
            ),
            ('monoamine_misc', 'Monoamine / Mixed Antidepressants', lambda m, c, n, a:
                catHas(c, 'antidepressant', 'antidepressants', 'mood stabilizer',
                         'other nervous system')
            ),
        ]),
        ('psychedelics', 'Psychedelics & Consciousness', [
            ('serotonergic_psy', 'Classical Psychedelics (5-HT2A)', lambda m, c, n, a:
                moaHas(m, 'serotonin 2a', '5-ht2a', '5ht2a', 'serotonin (5-ht) receptor')
                or nameIs(n, a, 'psilocybin', 'psilocin', 'psilocybine', 'lsd', 'dmt',
                            '5-meo-dmt', '5-bodmt', 'mescaline', '4-ho-met',
                            'ibogaine', 'noribogaine', 'ayahuasca')
            ),
            ('dissociatives', 'Dissociatives (NMDA Antagonists)', lambda m, c, n, a:
                nameIs(n, a, 'ketamine', 'esketamine', 'pcp', 'dxm', 'dextromethorphan',
                         'nitrous', 'memantine', 'mxe', 'tiletamine')
            ),
            ('empathogens', 'Empathogens / Entactogens', lambda m, c, n, a:
                nameIs(n, a, 'mdma', 'mda', 'mbdb', '5-mapb', '6-apb', '3,4-methylenedioxy')
            ),
            ('kappa_opi', 'Kappa Opioid / Psychotomimetics', lambda m, c, n, a:
                moaHas(m, 'kappa opioid', 'kor ')
                or nameIs(n, a, 'salvinorin', 'ibogaine', 'nalfurafine')
            ),
        ]),
        ('sleep', 'Sleep & Circadian', [
            ('melatonin_circ', 'Melatonin / Circadian', lambda m, c, n, a:
                moaHas(m, 'melatonin receptor', 'mt1', 'mt2')
                or catHas(c, 'melatonin', 'insomnia treatment', 'hypnotics and sedatives')
                or nameIs(n, a, 'melatonin', 'ramelteon', 'agomelatine', 'dsip',
                            'delta sleep', 'iodomelatonin', 'chloromelatonin',
                            'difluoroagomelatine')
            ),
            ('sleep_gaba', 'GABAergic Sedatives / Hypnotics', lambda m, c, n, a:
                (moaHas(m, 'gaba', 'gabaa') and catHas(c, 'hypnotic', 'sedative', 'insomnia'))
                or catHas(c, 'hypnotics and sedatives')
                or nameIs(n, a, 'zolpidem', 'eszopiclone', 'zaleplon', 'phenibut', 'ghb',
                            'baclofen')
            ),
            ('orexin', 'Orexin Antagonists', lambda m, c, n, a:
                moaHas(m, 'orexin', 'hypocretin')
                or catHas(c, 'orexin')
                or nameIs(n, a, 'suvorexant', 'lemborexant', 'daridorexant')
            ),
            ('adaptogens', 'Adaptogens & Stress', lambda m, c, n, a:
                catHas(c, 'adaptogen')
                or nameIs(n, a, 'ashwagandha', 'ashwagandhanolide', 'withania', 'rhodiola',
                            'eleuthero', 'ginseng', 'schisandra', 'l-theanine', 'theanine',
                            'phosphatidylserine')
            ),
        ]),
        ('longevity', 'Longevity & Neuroprotection', [
            ('nad_sirt', 'NAD⁺ / Sirtuins / AMPK', lambda m, c, n, a:
                moaHas(m, 'sirtuin', 'ampk', 'nad', 'parp', 'nampt')
                or nameIs(n, a, 'nicotinamide riboside', 'nicotinamide mononucleotide',
                            'betanmn', 'nmn', 'resveratrol', 'pterostilbene',
                            'berberine', 'dihydroberberine', 'oxyberberine',
                            'berberine chloride')
            ),
            ('mtor_autoph', 'mTOR / Rapamycin / Autophagy', lambda m, c, n, a:
                moaHas(m, 'mtor', 'fkbp', 'rapamycin', 'mammalian target')
                or nameIs(n, a, 'rapamycin', 'sirolimus', 'everolimus', 'temsirolimus',
                            'homotemsirolimus', '28-o-methylrapamycin')
            ),
            ('antioxidants', 'Antioxidants & ROS', lambda m, c, n, a:
                nameIs(n, a, 'quercetin', 'curcumin', 'resveratrol', 'pterostilbene',
                         'astaxanthin', 'coq10', 'ubiquinone', 'lipoic acid', 'nac',
                         'n-acetylcysteine', 'glutathione', 'methylquercetin',
                         'didemethylcurcumin', 'trismethoxyresveratrol',
                         'pentamethylquercetin', 'mono-o-demethylcurcumin',
                         '3-o-methylquercetin')
            ),
            ('bdnf_nt', 'BDNF / Neurotrophins', lambda m, c, n, a:
                moaHas(m, 'bdnf', 'ngf', 'neurotrophin', 'trkb', 'trka')
                or nameIs(n, a, 'acd856', 'cerebrolysin', 'nsi-189', 'semax')
            ),
            ('peptide_longevity', 'Longevity Peptides', lambda m, c, n, a:
                nameIs(n, a, 'epitalon', 'epithalon', 'thymalin', 'thymulin', 'dsip',
                         'pinealon', 'cortagen', 'vesugen')
            ),
        ]),
        ('metabolic', 'Metabolic & Body Composition', [
            ('insulin_glp', 'Insulin / GLP-1 / Diabetes', lambda m, c, n, a:
                moaHas(m, 'insulin receptor', 'glucagon', 'glp-1', 'sglt', 'dpp-4',
                          'dipeptidyl peptidase', 'dipeptidyl peptidase 4')
                or catHas(c, 'antidiabetic', 'insulin', 'blood glucose', 'hypoglycemic')
                or nameIs(n, a, 'metformin', 'semaglutide', 'liraglutide', 'tirzepatide',
                            'alogliptin', 'acarbose')
            ),
            ('lipid', 'Lipid Metabolism / Statins', lambda m, c, n, a:
                moaHas(m, 'hmg-coa', 'hmg coa', 'lipoprotein', 'ppar alpha', 'bile acid',
                          'cholesterol', 'farnesyl diphosphate')
                or catHas(c, 'statin', 'statins', 'lipid-lowering', 'lipid', 'dyslipidemia')
            ),
            ('thyroid', 'Thyroid Axis', lambda m, c, n, a:
                moaHas(m, 'thyroid receptor', 'tsh', 'thyroid hormone', 't3 receptor')
                or catHas(c, 'thyroid')
                or nameIs(n, a, 'liothyronine', 'levothyroxine', 'cytomel', 'thyroid')
            ),
            ('lipolysis', 'Lipolysis / Thermogenics', lambda m, c, n, a:
                moaHas(m, 'beta-2 adrenergic', 'beta-3 adrenergic')
                or nameIs(n, a, 'clenbuterol', 'ephedrine', 'yohimbine', 'beta-yohimbine',
                            'pseudoephedrine', 'phenylephrine', 'cardarine', 'sr9009')
            ),
            ('corticosteroids', 'Corticosteroids', lambda m, c, n, a:
                moaHas(m, 'glucocorticoid receptor', 'mineralocorticoid receptor')
                or catHas(c, 'corticosteroid', 'corticosteroids', 'anti-inflammatory')
            ),
        ]),
        ('cardiovascular', 'Cardiovascular', [
            ('beta_adren', 'Beta-Adrenergic Agents', lambda m, c, n, a:
                moaHas(m, 'beta-1 adrenergic', 'beta-2 adrenergic', 'adrenergic receptor beta',
                          'beta adrenoceptor')
                or catHas(c, 'beta blocker', 'beta blockers', 'beta agonist')
            ),
            ('calcium_ch', 'Calcium Channel Blockers', lambda m, c, n, a:
                moaHas(m, 'calcium channel', 'l-type calcium', 'voltage-gated calcium')
                or catHas(c, 'calcium channel blocker', 'calcium channel blockers')
            ),
            ('raas', 'RAAS / ACE / Angiotensin', lambda m, c, n, a:
                moaHas(m, 'angiotensin', 'angiotensin-converting', 'renin', 'ace ',
                          'type-1 angiotensin')
                or catHas(c, 'ace inhibitor', 'ace inhibitors', 'antihypertensive',
                            'antihypertensives')
            ),
            ('vasodilators', 'Vasodilators / NO Pathway / ED', lambda m, c, n, a:
                moaHas(m, 'phosphodiesterase 5', 'pde5', 'nitric oxide', 'nos ',
                          'guanylate cyclase', 'prostanoid', 'prostacyclin')
                or catHas(c, 'cardiac therapy', 'cardiovascular disease', 'vasodilator',
                            'vasoprotective', 'vasoprotectives')
                or nameIs(n, a, 'sildenafil', 'tadalafil', 'vardenafil', 'alprostadil',
                            'iloprost', 'nortadalafil')
            ),
            ('antiarrhythmic', 'Antiarrhythmics', lambda m, c, n, a:
                catHas(c, 'antiarrhythmic', 'atrial fibrillation')
            ),
            ('anticoag', 'Anticoagulants / Antiplatelet', lambda m, c, n, a:
                moaHas(m, 'purinergic receptor p2y12', 'thrombin', 'factor xa', 'platelet')
                or catHas(c, 'anticoagulant', 'antiplatelet', 'antithrombotic',
                            'myocardial infarction treatment')
            ),
        ]),
        ('immunology', 'Immunology & Inflammation', [
            ('cox_nsaid', 'COX Inhibitors / NSAIDs', lambda m, c, n, a:
                moaHas(m, 'cyclooxygenase', 'cyclooxygenase-2', 'cox-1', 'cox-2',
                          'prostaglandin', 'arachidonate 5-lipoxygenase')
                or catHas(c, 'nsaid', 'nsaids', 'anti-inflammatory', 'analgesic')
            ),
            ('cytokine', 'Cytokine / TNF / IL Modulators', lambda m, c, n, a:
                moaHas(m, 'interleukin', 'tnf', 'tumor necrosis factor', 'interferon',
                          'nf-kb', 'il-', 'macrophage colony')
                or catHas(c, 'immunosuppressant', 'immunomodulat', 'cytokine', 'anti-tnf',
                            'rheumatic disease')
            ),
            ('jaki', 'JAK / TYK Inhibitors', lambda m, c, n, a:
                moaHas(m, 'tyrosine-protein kinase jak', 'tyk2', 'janus kinase',
                          'tyrosine-protein kinase tyk')
                or catHas(c, 'jak inhibitor', 'jaki')
            ),
            ('mast_hist2', 'Antihistamines', lambda m, c, n, a:
                moaHas(m, 'histamine h1', 'histamine h2', 'histamine h3')
                or catHas(c, 'antihistamine', 'antihistamines', 'allergic disease')
            ),
        ]),
        ('oncology', 'Oncology', [
            ('kinase_inh', 'Kinase Inhibitors', lambda m, c, n, a:
                moaHas(m, 'tyrosine kinase', 'protein kinase', 'egfr', 'her2', 'mek ',
                          'raf ', 'ephrin', 'receptor protein-tyrosine kinase',
                          'vascular endothelial growth factor receptor',
                          'stem cell growth factor receptor',
                          'platelet-derived growth factor receptor',
                          'tyrosine-protein kinase receptor flt3',
                          'tyrosine-protein kinase receptor ret',
                          'alk tyrosine kinase')
                or catHas(c, 'kinase inhibitor', 'antineoplastics', 'anticancer',
                            'antitumor', 'neoplasm treatment', 'renal cell carcinoma',
                            'non-small cell lung')
            ),
            ('hormone_cancer', 'Hormone-Sensitive Cancer', lambda m, c, n, a:
                catHas(c, 'breast carcinoma', 'breast neoplasm', 'prostate cancer',
                         'hormone-sensitive', 'endocrine therapy', 'androgen deprivation',
                         'adrenal cortex')
            ),
            ('hdac', 'HDAC Inhibitors / Epigenetic', lambda m, c, n, a:
                moaHas(m, 'histone deacetylase', 'hdac')
            ),
            ('smoothened', 'Hedgehog / Smoothened', lambda m, c, n, a:
                moaHas(m, 'smoothened')
            ),
        ]),
        ('antimicrobial', 'Antimicrobial', [
            ('antibacterial', 'Antibacterial', lambda m, c, n, a:
                moaHas(m, 'bacterial', 'bacterial urease', 'dna gyrase',
                          'penicillin', 'beta-lactam', 'bacterial penicillin')
                or catHas(c, 'antibiotic', 'antibacterial', 'antibiotics', 'beta-lactam',
                            'cephalosporin', 'quinolone', 'aminoglycoside',
                            'osteomyelitis', 'antibiotics (dermatological)')
            ),
            ('antiviral', 'Antiviral', lambda m, c, n, a:
                moaHas(m, 'viral', 'hiv', 'hepatitis', 'influenza', 'rna-dependent')
                or catHas(c, 'antiviral', 'antivirals', 'aids', 'hiv')
            ),
            ('antifungal', 'Antifungal', lambda m, c, n, a:
                moaHas(m, 'fungal', 'lanosterol', 'ergosterol')
                or catHas(c, 'antifungal', 'antifungals', 'tinea', 'fungal')
            ),
        ]),
        ('ophth', 'Ophthalmology & Other', [
            ('ophthalm', 'Ophthalmologicals', lambda m, c, n, a:
                catHas(c, 'ophthalmolog', 'ocular', 'glaucoma', 'macular')
            ),
            ('derm', 'Dermatological', lambda m, c, n, a:
                catHas(c, 'dermatolog', 'acne', 'skin disease', 'eczema')
            ),
            ('gi', 'Gastrointestinal', lambda m, c, n, a:
                catHas(c, 'gastrointestinal', 'antispasmodic', 'antidiarrheal',
                         'antidiarrheals', 'nausea')
            ),
            ('resp', 'Respiratory', lambda m, c, n, a:
                catHas(c, 'airway obstruction', 'bronchospasm', 'obstructive airway',
                         'chronic obstructive', 'nasal', 'respiratory')
            ),
            ('urology', 'Urology / Reproductive', lambda m, c, n, a:
                catHas(c, 'urolog', 'bladder', 'benign prostatic', 'gynecolog',
                         'reproductive', 'obstetric')
            ),
        ]),
    ]


class Command(BaseCommand):
    help = 'Populate CompoundTaxonomyTag and seed steroid ratings for the stack builder'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true',
                            help='Delete all existing taxonomy tags before re-populating')

    def handle(self, *args, **options):
        if options['clear']:
            n = CompoundTaxonomyTag.objects.all().delete()[0]
            self.stdout.write(f'Cleared {n} taxonomy tags')

        self._populate_steroid_ratings()
        self._populate_taxonomy_tags()

    # ── Steroid ratings ───────────────────────────────────────────────────────

    def _populate_steroid_ratings(self):
        self.stdout.write('Populating steroid ratings…')
        created = updated = 0
        for name_key, (anabolic, androgenic) in STEROID_RATINGS.items():
            compounds = Compound.objects.filter(name__iexact=name_key)
            if not compounds.exists():
                # Fallback: case-insensitive contains
                compounds = Compound.objects.filter(name__icontains=name_key)
            for compound in compounds:
                obj, was_created = CompoundSteroidRating.objects.get_or_create(compound=compound)
                obj.anabolic_rating  = anabolic
                obj.androgenic_rating = androgenic
                obj.save(update_fields=['anabolic_rating', 'androgenic_rating'])
                if was_created:
                    created += 1
                else:
                    updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'  Steroid ratings: {created} created, {updated} updated'
        ))

    # ── Taxonomy tags ─────────────────────────────────────────────────────────

    def _populate_taxonomy_tags(self):
        self.stdout.write('Building taxonomy index…')
        taxonomy = _taxonomy()

        # Load all builder compounds with prefetched relations in one query
        from django.db.models import Q
        # Re-use the same filter logic as StackBuilderView
        from stacks.views import StackBuilderView
        v = StackBuilderView()
        target_q = Q()
        for kw in v._TARGET_KEYWORDS:
            target_q |= Q(mechanism_of_action__target_name__name__icontains=kw)
        cat_q = Q()
        for kw in v._CATEGORY_KEYWORDS:
            cat_q |= Q(categories__name__icontains=kw)
        name_q = Q()
        for kw in v._NAME_KEYWORDS:
            name_q |= Q(name__icontains=kw)
        matched_ids = set(
            Compound.objects.filter(target_q | cat_q | name_q)
            .distinct().values_list('pk', flat=True)
        )

        compounds_qs = (
            Compound.objects
            .filter(pk__in=matched_ids)
            .prefetch_related('categories', 'mechanism_of_action__target_name')
            .only('id', 'name', 'aliases')
        )

        total = compounds_qs.count()
        self.stdout.write(f'  Processing {total} compounds…')

        tags_to_create = []
        existing_keys  = set(
            CompoundTaxonomyTag.objects
            .filter(compound_id__in=matched_ids)
            .values_list('compound_id', 'sub_id')
        )

        for compound in compounds_qs.iterator(chunk_size=500):
            moa_list  = [
                moa.target_name.name
                for moa in compound.mechanism_of_action.all()
                if moa.target_name
            ]
            cats_list = [cat.name for cat in compound.categories.all()]
            name      = compound.name or ''
            aka       = compound.aliases or ''

            for group_id, group_label, subs in taxonomy:
                for sub_id, sub_label, match_fn in subs:
                    key = (compound.pk, sub_id)
                    if key in existing_keys:
                        continue
                    try:
                        if match_fn(moa_list, cats_list, name, aka):
                            tags_to_create.append(CompoundTaxonomyTag(
                                compound_id=compound.pk,
                                group_id=group_id,
                                sub_id=sub_id,
                                group_label=group_label,
                                sub_label=sub_label,
                            ))
                    except Exception:
                        pass

        with transaction.atomic():
            CompoundTaxonomyTag.objects.bulk_create(
                tags_to_create, ignore_conflicts=True, batch_size=2000
            )

        self.stdout.write(self.style.SUCCESS(
            f'  Taxonomy tags: {len(tags_to_create)} new records created'
        ))
