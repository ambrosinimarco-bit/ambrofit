-- Aggiunge colonna per le calorie totali giornaliere da iPhone Fitness
-- (include già BMR + movimento + sport — inserite manualmente dall'utente)
ALTER TABLE daily_health ADD COLUMN IF NOT EXISTS total_calories_iphone INT;
