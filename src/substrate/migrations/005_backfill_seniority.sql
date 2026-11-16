-- 005_backfill_seniority.sql — existing positions predate the classifier, so
-- their seniority is NULL and the first promotion after deploy stays silent.
-- Backfill mirrors substrate/seniority.py's precedence (most specific first);
-- unknown → NULL (never guessed). Only fills NULLs — never overwrites.
-- NOTE: updates closed, transaction-time-historical versions in place.
-- seniority is derived, so this is not a bitemporal violation, but the
-- first detect run after this WILL emit promotion events for those rows:
-- pair the deploy with `substrate detect --first-run`.

UPDATE positions SET seniority = CASE
    WHEN lower(title_norm) ~ '\m(chief|cto|ceo|cfo|coo|cmo|cro|c-suite)\M' THEN 'c_level'
    WHEN lower(title_norm) ~ '\m(svp|senior vice president|evp|executive vice president)\M' THEN 'svp'
    WHEN lower(title_norm) ~ '\m(vp|vice president)\M' THEN 'vp'
    WHEN lower(title_norm) ~ '\m(senior director|sr\. director)\M' THEN 'senior_director'
    WHEN lower(title_norm) ~ '\mdirector\M' THEN 'director'
    WHEN lower(title_norm) ~ '\m(senior manager|sr\. manager)\M' THEN 'senior_manager'
    WHEN lower(title_norm) ~ '\mmanager\M' THEN 'manager'
    WHEN lower(title_norm) ~ '\m(principal|staff engineer|distinguished)\M' THEN 'principal'
    WHEN lower(title_norm) ~ '\m(lead|head of)\M' THEN 'lead'
    WHEN lower(title_norm) ~ '\m(senior|sr\.|sr)\M' THEN 'senior_ic'
    WHEN lower(title_norm) ~ '\m(intern|apprentice)\M' THEN 'intern'
    WHEN lower(title_norm) ~ '\m(engineer|developer|designer|analyst|associate|account executive|specialist|coordinator|consultant|architect|scientist|recruiter|administrator|executive)\M' THEN 'ic'
    ELSE NULL
END
WHERE seniority IS NULL;
