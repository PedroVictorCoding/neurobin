-- SQLite queries to clean up organisms
-- 
-- Part 1: Remove all targets that are NOT Homo sapiens
-- This will also cascade to remove related compound-target interactions
--

BEGIN TRANSACTION;

-- First, let's see what organisms we have
SELECT DISTINCT organism, COUNT(*) as count 
FROM compounds_target 
WHERE organism != '' 
GROUP BY organism 
ORDER BY count DESC;

-- Remove targets that are not Homo sapiens (but keep empty organism entries)
DELETE FROM compounds_target 
WHERE organism != '' 
AND organism != 'Homo sapiens';

-- Part 2: Remove compound mechanisms for blacklisted organisms
-- (These are mechanisms that reference targets from specific organisms)
--

-- Remove compound mechanisms that reference targets from blacklisted organisms
DELETE FROM compounds_compoundmechanismofaction 
WHERE target_name_id IN (
    SELECT id FROM compounds_target 
    WHERE organism IN (
        'Mus musculus',
        'Rattus norvegicus', 
        'Homo sapiens',
        'Cavia porcellus',
        'Oryctolagus cuniculus'
    )
);

-- Alternative approach: Remove by target organism directly
-- (in case the above doesn't work due to foreign key constraints)
DELETE FROM compounds_compoundmechanismofaction 
WHERE target_name_id IN (
    SELECT id FROM compounds_target 
    WHERE organism = 'Mus musculus'
    OR organism = 'Rattus norvegicus'
    OR organism = 'Homo sapiens' 
    OR organism = 'Cavia porcellus'
    OR organism = 'Oryctolagus cuniculus'
);

COMMIT;

-- Verification queries
SELECT 'Remaining organisms in targets:' as info;
SELECT DISTINCT organism, COUNT(*) as count 
FROM compounds_target 
WHERE organism != '' 
GROUP BY organism 
ORDER BY count DESC;

SELECT 'Total targets remaining:' as info;
SELECT COUNT(*) as total_targets FROM compounds_target;

SELECT 'Total mechanisms remaining:' as info;
SELECT COUNT(*) as total_mechanisms FROM compounds_compoundmechanismofaction;
