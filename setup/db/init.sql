-- for new docker image, put this as init.sql

-- meter table
CREATE TABLE IF NOT EXISTS meter (
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hostname VARCHAR(16) NOT NULL UNIQUE,
    meter_type VARCHAR(16) NOT NULL DEFAULT '', 
    system_version INT NOT NULL DEFAULT -1 ,
    subsystem_version INT NOT NULL DEFAULT -1,
    modules JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    last_updated TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);

-- meter firmwares obsolete table
CREATE TABLE IF NOT EXISTS meter_firmware (
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    meter_id INT NOT NULL REFERENCES meter(id),
    name VARCHAR(64) NOT NULL,
    version INT NOT NULL,
    modfunc INT NOT NULL DEFAULT -1,
    fullid INT NOT NULL DEFAULT -1,
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    last_updated TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    UNIQUE(meter_id, name)
);

-- revised meter jobs table
CREATE TABLE IF NOT EXISTS meter_job (
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    meter_id INT NOT NULL REFERENCES meter(id),
    name VARCHAR(64) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('missing','n/a','pass','fail')),
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);


CREATE INDEX IF NOT EXISTS idx_meter_firmware_meter_id ON meter_firmware(meter_id);
CREATE INDEX IF NOT EXISTS idx_meter_job_meter_id ON meter_job(meter_id);


