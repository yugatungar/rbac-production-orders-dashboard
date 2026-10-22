-- Starting roles and page permissions. Re-running resets them to these values.

TRUNCATE TABLE APP_ROLES;
INSERT INTO APP_ROLES (ROLE_NAME, DESCRIPTION, ROW_SCOPE) VALUES
    ('LEADERSHIP', 'Executive view, summary only', 'ALL'),
    ('ANALYST',    'Detailed read-only analysis', 'ALL'),
    ('OPERATOR',   'Maintains own data',          'OWN'),
    ('DEVELOPER',  'Data explorer and inspector', 'ALL'),
    ('ADMIN',      'Full access and user management', 'ALL');

TRUNCATE TABLE ROLE_PAGE_ACCESS;
INSERT INTO ROLE_PAGE_ACCESS (ROLE_NAME, PAGE_NAME) VALUES
    ('LEADERSHIP', 'Executive'),
    ('ANALYST',    'Executive'),
    ('ANALYST',    'Analysis'),
    ('ANALYST',    'Data'),
    ('OPERATOR',   'Data'),
    ('DEVELOPER',  'Analysis'),
    ('DEVELOPER',  'Data'),
    ('DEVELOPER',  'Developer'),
    ('ADMIN',      'Executive'),
    ('ADMIN',      'Analysis'),
    ('ADMIN',      'Data'),
    ('ADMIN',      'Developer'),
    ('ADMIN',      'Admin');