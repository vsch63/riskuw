--
-- PostgreSQL database dump
--


-- Dumped from database version 14.22 (Ubuntu 14.22-0ubuntu0.22.04.1)
-- Dumped by pg_dump version 14.22 (Ubuntu 14.22-0ubuntu0.22.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: audit_trail_immutable(); Type: FUNCTION; Schema: public; Owner: uw_user
--

CREATE FUNCTION public.audit_trail_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
                BEGIN
                    RAISE EXCEPTION
                        'audit_trail is immutable — UPDATE and DELETE are not permitted';
                END;
                $$;


ALTER FUNCTION public.audit_trail_immutable() OWNER TO uw_user;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: applicant_master; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.applicant_master (
    id integer NOT NULL,
    applicant_ref character varying(100) NOT NULL,
    full_name character varying(200),
    email character varying(200),
    phone character varying(40),
    dob date,
    gender character varying(10),
    address_line1 character varying(255),
    address_line2 character varying(255),
    city character varying(100),
    state character varying(10),
    pincode character varying(20),
    country character varying(60) DEFAULT 'India'::character varying,
    source character varying(40) DEFAULT 'UPLOAD'::character varying,
    uploaded_by character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.applicant_master OWNER TO uw_user;

--
-- Name: applicant_master_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.applicant_master_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.applicant_master_id_seq OWNER TO uw_user;

--
-- Name: applicant_master_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.applicant_master_id_seq OWNED BY public.applicant_master.id;


--
-- Name: application; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.application (
    application_number character varying(30) NOT NULL,
    product_type character varying(30) NOT NULL,
    product_code character varying(20),
    channel character varying(30) NOT NULL,
    applicant_ref character varying(100) NOT NULL,
    age smallint NOT NULL,
    gender character varying(20) NOT NULL,
    state character varying(2) NOT NULL,
    citizenship character varying(2) NOT NULL,
    face_amount numeric(15,2) NOT NULL,
    coverage_term_yrs smallint,
    is_replacement boolean NOT NULL,
    status character varying(30) NOT NULL,
    submitted_at timestamp with time zone,
    source_ip inet,
    raw_payload jsonb,
    pas_policy_id character varying(100),
    agent_id character varying(100),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) NOT NULL,
    updated_by character varying(100) NOT NULL,
    version bigint NOT NULL,
    is_deleted boolean NOT NULL,
    tenant_id uuid NOT NULL,
    CONSTRAINT chk_application_status CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'SUBMITTED'::character varying, 'IN_REVIEW'::character varying, 'PENDING_REQUIREMENTS'::character varying, 'APPROVED'::character varying, 'DECLINED'::character varying, 'POSTPONED'::character varying, 'WITHDRAWN'::character varying, 'EXPIRED'::character varying])::text[])))
);


ALTER TABLE public.application OWNER TO uw_user;

--
-- Name: aps_letter_templates; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.aps_letter_templates (
    id character varying(40) NOT NULL,
    template_name character varying(120) NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    subject character varying(250) NOT NULL,
    body_text text NOT NULL,
    footer_text text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.aps_letter_templates OWNER TO uw_user;

--
-- Name: aps_request; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.aps_request (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    application_id uuid NOT NULL,
    rule_id character varying(50),
    rule_name character varying(200),
    physician_name character varying(200),
    physician_address text,
    physician_phone character varying(30),
    requested_at timestamp without time zone DEFAULT now(),
    received_at timestamp without time zone,
    status character varying(30) DEFAULT 'PENDING'::character varying,
    notes text,
    document_ref character varying(200),
    created_by character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.aps_request OWNER TO uw_user;

--
-- Name: audit_event; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.audit_event (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    event_id uuid NOT NULL,
    event_type character varying(100) NOT NULL,
    event_category character varying(50) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id uuid NOT NULL,
    actor_type character varying(30) NOT NULL,
    actor_id character varying(100) NOT NULL,
    actor_ip inet,
    before_state jsonb,
    after_state jsonb,
    event_metadata jsonb,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.audit_event OWNER TO uw_user;

--
-- Name: audit_trail; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.audit_trail (
    id bigint NOT NULL,
    event_id character varying(40) DEFAULT (gen_random_uuid())::text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    event_category character varying(40) NOT NULL,
    event_type character varying(80) NOT NULL,
    actor_username character varying(100),
    actor_role character varying(40),
    actor_ip character varying(60),
    tenant_id character varying(40),
    entity_type character varying(60),
    entity_id character varying(100),
    entity_ref character varying(200),
    before_state jsonb,
    after_state jsonb,
    event_metadata jsonb,
    outcome character varying(20) DEFAULT 'SUCCESS'::character varying,
    failure_reason text,
    source character varying(20) DEFAULT 'UI'::character varying
);


ALTER TABLE public.audit_trail OWNER TO uw_user;

--
-- Name: audit_trail_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.audit_trail_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.audit_trail_id_seq OWNER TO uw_user;

--
-- Name: audit_trail_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.audit_trail_id_seq OWNED BY public.audit_trail.id;


--
-- Name: batch_job; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_job (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    job_number character varying(30) NOT NULL,
    job_name character varying(200),
    status character varying(30) DEFAULT 'PENDING'::character varying,
    mode character varying(20) DEFAULT 'BATCH'::character varying,
    input_filename character varying(300),
    input_format character varying(10),
    total_records integer DEFAULT 0,
    processed integer DEFAULT 0,
    approved integer DEFAULT 0,
    declined integer DEFAULT 0,
    referred integer DEFAULT 0,
    errored integer DEFAULT 0,
    skipped integer DEFAULT 0,
    dry_run boolean DEFAULT false,
    submitted_by character varying(100),
    submitted_at timestamp without time zone DEFAULT now(),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    config_json jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    scheduled_at timestamp without time zone,
    schedule_label character varying(100)
);


ALTER TABLE public.batch_job OWNER TO uw_user;

--
-- Name: batch_job_records; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_job_records (
    id integer NOT NULL,
    job_id character varying(40) NOT NULL,
    row_number integer,
    applicant_ref character varying(100),
    product_code character varying(20),
    status character varying(20),
    outcome character varying(30),
    risk_class character varying(30),
    net_debit_points integer,
    primary_reason text,
    error_codes text,
    processing_ms integer,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.batch_job_records OWNER TO uw_user;

--
-- Name: batch_job_records_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.batch_job_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.batch_job_records_id_seq OWNER TO uw_user;

--
-- Name: batch_job_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.batch_job_records_id_seq OWNED BY public.batch_job_records.id;


--
-- Name: batch_jobs; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_jobs (
    id character varying(40) DEFAULT (gen_random_uuid())::text NOT NULL,
    job_number character varying(20) NOT NULL,
    job_name character varying(200),
    status character varying(20) DEFAULT 'QUEUED'::character varying NOT NULL,
    total_records integer DEFAULT 0 NOT NULL,
    processed_count integer DEFAULT 0 NOT NULL,
    approved_count integer DEFAULT 0 NOT NULL,
    declined_count integer DEFAULT 0 NOT NULL,
    referred_count integer DEFAULT 0 NOT NULL,
    errored_count integer DEFAULT 0 NOT NULL,
    dry_run boolean DEFAULT false NOT NULL,
    skip_product_errors boolean DEFAULT false NOT NULL,
    input_filename character varying(255),
    error_message text,
    submitted_by character varying(100),
    submitted_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    policy_effective_date date,
    policy_expire_date date
);


ALTER TABLE public.batch_jobs OWNER TO uw_user;

--
-- Name: batch_record; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_record (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    row_number integer NOT NULL,
    applicant_ref character varying(100),
    status character varying(30) DEFAULT 'PENDING'::character varying,
    input_data jsonb,
    validation_errors jsonb,
    outcome character varying(40),
    risk_class character varying(30),
    net_debit_points integer,
    table_rating smallint,
    flat_extra numeric(8,4),
    approved_premium numeric(12,4),
    primary_reason text,
    findings_json jsonb,
    case_number character varying(30),
    processing_ms integer,
    error_codes jsonb,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.batch_record OWNER TO uw_user;

--
-- Name: batch_recurring_schedules; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_recurring_schedules (
    id integer NOT NULL,
    schedule_name character varying(200),
    cron_expression character varying(100),
    status character varying(20) DEFAULT 'ACTIVE'::character varying,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.batch_recurring_schedules OWNER TO uw_user;

--
-- Name: batch_recurring_schedules_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.batch_recurring_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.batch_recurring_schedules_id_seq OWNER TO uw_user;

--
-- Name: batch_recurring_schedules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.batch_recurring_schedules_id_seq OWNED BY public.batch_recurring_schedules.id;


--
-- Name: batch_scheduled_jobs; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.batch_scheduled_jobs (
    id integer NOT NULL,
    job_name character varying(200),
    run_at timestamp with time zone,
    status character varying(20) DEFAULT 'PENDING'::character varying,
    dry_run boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.batch_scheduled_jobs OWNER TO uw_user;

--
-- Name: batch_scheduled_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.batch_scheduled_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.batch_scheduled_jobs_id_seq OWNER TO uw_user;

--
-- Name: batch_scheduled_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.batch_scheduled_jobs_id_seq OWNED BY public.batch_scheduled_jobs.id;


--
-- Name: custom_rule_history; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.custom_rule_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    rule_id character varying(100) NOT NULL,
    rule_version character varying(20) NOT NULL,
    name character varying(200) NOT NULL,
    category character varying(50) NOT NULL,
    logic character varying(10) NOT NULL,
    conditions jsonb NOT NULL,
    action jsonb NOT NULL,
    status character varying(20) NOT NULL,
    changed_by character varying(100) NOT NULL,
    change_type character varying(30) NOT NULL,
    change_notes text,
    snapshot_at timestamp with time zone DEFAULT now(),
    effective_date timestamp with time zone,
    expiry_date timestamp with time zone
);


ALTER TABLE public.custom_rule_history OWNER TO uw_user;

--
-- Name: custom_uw_rule; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.custom_uw_rule (
    tenant_id uuid NOT NULL,
    product_code character varying(50),
    rule_id character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    category character varying(50) NOT NULL,
    logic character varying(10) NOT NULL,
    is_enabled boolean NOT NULL,
    priority integer NOT NULL,
    conditions jsonb NOT NULL,
    action jsonb NOT NULL,
    effective_date timestamp with time zone,
    expiry_date timestamp with time zone,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) DEFAULT '00000000-0000-0000-0000-000000000001'::character varying NOT NULL,
    updated_by character varying(100) DEFAULT 'system'::character varying NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    status character varying(20) DEFAULT 'DEPLOYED'::character varying NOT NULL,
    rule_version character varying(20) DEFAULT '1.0'::character varying NOT NULL,
    reviewed_by character varying(100),
    reviewed_at timestamp with time zone,
    approved_by character varying(100),
    approved_at timestamp with time zone,
    deployed_at timestamp with time zone,
    change_notes text
);


ALTER TABLE public.custom_uw_rule OWNER TO uw_user;

--
-- Name: error_code; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.error_code (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    error_number integer NOT NULL,
    error_code character varying(30) NOT NULL,
    category character varying(30) NOT NULL,
    severity character varying(20) DEFAULT 'ERROR'::character varying NOT NULL,
    description text NOT NULL,
    resolution_hint text,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.error_code OWNER TO uw_user;

--
-- Name: error_codes; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.error_codes (
    id integer NOT NULL,
    error_number integer NOT NULL,
    error_code character varying(30) NOT NULL,
    category character varying(30) DEFAULT 'ELIGIBILITY'::character varying NOT NULL,
    severity character varying(10) DEFAULT 'ERROR'::character varying NOT NULL,
    description text NOT NULL,
    resolution_hint text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.error_codes OWNER TO uw_user;

--
-- Name: error_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.error_codes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.error_codes_id_seq OWNER TO uw_user;

--
-- Name: error_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.error_codes_id_seq OWNED BY public.error_codes.id;


--
-- Name: letter_template; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.letter_template (
    tenant_id uuid NOT NULL,
    outcome character varying(30) NOT NULL,
    template_name character varying(100) NOT NULL,
    is_active boolean NOT NULL,
    header_company_name character varying(200),
    header_tagline character varying(300),
    footer_text text,
    contact_email character varying(200),
    contact_phone character varying(50),
    body_text text,
    next_steps jsonb,
    custom_fields jsonb,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) NOT NULL,
    updated_by character varying(100) NOT NULL,
    version bigint NOT NULL,
    is_deleted boolean NOT NULL
);


ALTER TABLE public.letter_template OWNER TO uw_user;

--
-- Name: letter_templates; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.letter_templates (
    id character varying(40) NOT NULL,
    template_name character varying(120) NOT NULL,
    outcome character varying(40) NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    header_company_name character varying(120),
    header_tagline character varying(200),
    contact_email character varying(120),
    contact_phone character varying(40),
    body_text text,
    next_steps text,
    footer_text text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.letter_templates OWNER TO uw_user;

--
-- Name: login_attempts; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.login_attempts (
    username character varying(100) NOT NULL,
    failed_count integer DEFAULT 0 NOT NULL,
    last_failed_at timestamp with time zone,
    locked_until timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.login_attempts OWNER TO uw_user;

--
-- Name: member_upload_log; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.member_upload_log (
    id integer NOT NULL,
    upload_ref character varying(40) NOT NULL,
    filename character varying(255),
    total_rows integer DEFAULT 0,
    inserted integer DEFAULT 0,
    updated integer DEFAULT 0,
    skipped integer DEFAULT 0,
    errors integer DEFAULT 0,
    uploaded_by character varying(100),
    uploaded_at timestamp with time zone DEFAULT now(),
    notes text
);


ALTER TABLE public.member_upload_log OWNER TO uw_user;

--
-- Name: member_upload_log_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.member_upload_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.member_upload_log_id_seq OWNER TO uw_user;

--
-- Name: member_upload_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.member_upload_log_id_seq OWNED BY public.member_upload_log.id;


--
-- Name: mfa_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.mfa_config (
    username character varying(100) NOT NULL,
    totp_secret character varying(64) NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    is_verified boolean DEFAULT false NOT NULL,
    backup_codes text[],
    enabled_at timestamp with time zone,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mfa_config OWNER TO uw_user;

--
-- Name: notification_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.notification_config (
    event character varying(60) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    recipients text,
    subject_tpl text,
    body_tpl text,
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.notification_config OWNER TO uw_user;

--
-- Name: notification_log; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.notification_log (
    id integer NOT NULL,
    event character varying(60),
    recipient character varying(200),
    subject character varying(300),
    status character varying(20),
    error_msg text,
    sent_at timestamp with time zone DEFAULT now(),
    error_code character varying(20),
    applicant_ref character varying(100),
    batch_job_name character varying(200)
);


ALTER TABLE public.notification_log OWNER TO uw_user;

--
-- Name: notification_log_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.notification_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.notification_log_id_seq OWNER TO uw_user;

--
-- Name: notification_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.notification_log_id_seq OWNED BY public.notification_log.id;


--
-- Name: output_interface_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.output_interface_config (
    key character varying(60) NOT NULL,
    value text
);


ALTER TABLE public.output_interface_config OWNER TO uw_user;

--
-- Name: physicians; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.physicians (
    id integer NOT NULL,
    physician_name character varying(200) NOT NULL,
    registration_no character varying(60),
    specialisation character varying(100),
    clinic_name character varying(200),
    email character varying(200),
    phone character varying(40),
    address_line1 character varying(200),
    address_line2 character varying(200),
    city character varying(100),
    state character varying(10),
    pincode character varying(20),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    effective_date date,
    expire_date date
);


ALTER TABLE public.physicians OWNER TO uw_user;

--
-- Name: physicians_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.physicians_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.physicians_id_seq OWNER TO uw_user;

--
-- Name: physicians_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.physicians_id_seq OWNED BY public.physicians.id;


--
-- Name: policy_admin_queue; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.policy_admin_queue (
    id integer NOT NULL,
    applicant_ref character varying(100),
    applicant_name character varying(200),
    applicant_email character varying(200),
    case_id character varying(40),
    job_id character varying(40),
    product_code character varying(40),
    face_amount numeric(15,2),
    age integer,
    gender character varying(10),
    state character varying(10),
    outcome character varying(40),
    risk_class character varying(40),
    net_debit_points integer,
    approved_premium numeric(15,2),
    effective_date date,
    expire_date date,
    decision_date timestamp with time zone DEFAULT now(),
    reason text,
    source character varying(20) DEFAULT 'ONLINE'::character varying,
    status character varying(20) DEFAULT 'UNPROCESSED'::character varying,
    processed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    push_status character varying(20) DEFAULT 'PENDING'::character varying,
    push_attempts integer DEFAULT 0,
    push_last_error text,
    push_last_at timestamp with time zone
);


ALTER TABLE public.policy_admin_queue OWNER TO uw_user;

--
-- Name: policy_admin_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.policy_admin_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.policy_admin_queue_id_seq OWNER TO uw_user;

--
-- Name: policy_admin_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.policy_admin_queue_id_seq OWNED BY public.policy_admin_queue.id;


--
-- Name: premium_rate_table; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.premium_rate_table (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(20) NOT NULL,
    gender character varying(10) NOT NULL,
    tobacco_status character varying(20) DEFAULT 'NON_TOBACCO'::character varying NOT NULL,
    age_min smallint NOT NULL,
    age_max smallint NOT NULL,
    term_years smallint,
    risk_class character varying(30) DEFAULT 'STANDARD'::character varying NOT NULL,
    table_rating smallint DEFAULT 0,
    rate_per_thou numeric(10,4) NOT NULL,
    flat_extra_rate numeric(10,4) DEFAULT 0,
    effective_date timestamp without time zone DEFAULT now(),
    expiry_date timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    rate_label character varying(100),
    source character varying(100)
);


ALTER TABLE public.premium_rate_table OWNER TO uw_user;

--
-- Name: product; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(20) NOT NULL,
    product_name character varying(200) NOT NULL,
    category character varying(50),
    sub_type character varying(50),
    uw_method character varying(50),
    min_age integer,
    max_age integer,
    min_face numeric(15,2),
    max_face numeric(15,2),
    is_active boolean NOT NULL,
    is_gi boolean NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    effective_date timestamp without time zone DEFAULT now(),
    expiry_date timestamp without time zone
);


ALTER TABLE public.product OWNER TO uw_user;

--
-- Name: product_build_table; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_build_table (
    id integer NOT NULL,
    product_code character varying(20) NOT NULL,
    bmi_min numeric(5,2) NOT NULL,
    bmi_max numeric(5,2) NOT NULL,
    debit_points integer DEFAULT 0 NOT NULL,
    is_decline boolean DEFAULT false NOT NULL,
    band_label character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.product_build_table OWNER TO uw_user;

--
-- Name: product_build_table_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.product_build_table_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.product_build_table_id_seq OWNER TO uw_user;

--
-- Name: product_build_table_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.product_build_table_id_seq OWNED BY public.product_build_table.id;


--
-- Name: product_build_tables; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_build_tables (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(50) NOT NULL,
    bmi_min double precision NOT NULL,
    bmi_max double precision NOT NULL,
    debit_points integer NOT NULL,
    is_decline boolean NOT NULL,
    band_label character varying(100),
    sort_order integer NOT NULL,
    created_by character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_by character varying(100),
    updated_at timestamp without time zone
);


ALTER TABLE public.product_build_tables OWNER TO uw_user;

--
-- Name: product_decision_thresholds; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_decision_thresholds (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(50) NOT NULL,
    refer_threshold integer NOT NULL,
    decline_threshold integer NOT NULL,
    stp_threshold integer NOT NULL,
    max_table_rating integer NOT NULL,
    max_flat_extra double precision NOT NULL,
    allow_permanent_flat_extra boolean NOT NULL,
    allow_exclusion_riders boolean NOT NULL,
    max_income_multiple integer NOT NULL,
    max_net_worth_multiple double precision NOT NULL,
    large_face_threshold double precision NOT NULL,
    config_notes text,
    version integer NOT NULL,
    created_by character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_by character varying(100),
    updated_at timestamp without time zone,
    effective_date timestamp without time zone DEFAULT now(),
    expiry_date timestamp without time zone
);


ALTER TABLE public.product_decision_thresholds OWNER TO uw_user;

--
-- Name: product_rule_config_audit; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_rule_config_audit (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(50) NOT NULL,
    rule_id character varying(50),
    change_type character varying(50) NOT NULL,
    action character varying(50) NOT NULL,
    before_value text,
    after_value text,
    changed_by character varying(100) NOT NULL,
    change_reason text,
    changed_at timestamp without time zone NOT NULL,
    ip_address character varying(50),
    session_id character varying(100)
);


ALTER TABLE public.product_rule_config_audit OWNER TO uw_user;

--
-- Name: product_rule_configs; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_rule_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    product_code character varying(50) NOT NULL,
    rule_id character varying(50) NOT NULL,
    rule_name character varying(200),
    is_enabled boolean NOT NULL,
    debit_points_override integer,
    credit_points_override integer,
    flat_extra_override double precision,
    flat_extra_years_override integer,
    flat_extra_permanent_override boolean,
    hard_stop_action_override character varying(20),
    hard_stop_override boolean,
    requires_aps_override boolean,
    aps_reason_override character varying(500),
    config_notes text,
    effective_date timestamp without time zone NOT NULL,
    expiry_date timestamp without time zone,
    version integer NOT NULL,
    created_by character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_by character varying(100),
    updated_at timestamp without time zone
);


ALTER TABLE public.product_rule_configs OWNER TO uw_user;

--
-- Name: product_rules; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.product_rules (
    id integer NOT NULL,
    product_code character varying(20) NOT NULL,
    rule_id character varying(20) NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    debit_points_override integer,
    debit_override_active boolean DEFAULT false,
    flat_extra_override numeric(10,2),
    flat_extra_override_active boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.product_rules OWNER TO uw_user;

--
-- Name: product_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.product_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.product_rules_id_seq OWNER TO uw_user;

--
-- Name: product_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.product_rules_id_seq OWNED BY public.product_rules.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.products (
    product_code character varying(20) NOT NULL,
    product_name character varying(120) NOT NULL,
    product_type character varying(40) DEFAULT 'individual'::character varying NOT NULL,
    uw_method character varying(40) DEFAULT 'debit_points'::character varying NOT NULL,
    min_age integer DEFAULT 18 NOT NULL,
    max_age integer DEFAULT 70 NOT NULL,
    min_face_amount numeric(15,2) DEFAULT 0 NOT NULL,
    max_face_amount numeric(15,2) DEFAULT 10000000 NOT NULL,
    available_terms text,
    exam_required boolean DEFAULT false NOT NULL,
    non_medical_limit numeric(15,2),
    reinsurance_threshold numeric(15,2),
    max_issue_age integer,
    stp_threshold integer DEFAULT 50 NOT NULL,
    refer_threshold integer DEFAULT 150 NOT NULL,
    decline_threshold integer DEFAULT 300 NOT NULL,
    is_guaranteed_issue boolean DEFAULT false NOT NULL,
    is_group_product boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    description text,
    uw_notes text,
    effective_date date,
    expire_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    category character varying(50)
);


ALTER TABLE public.products OWNER TO uw_user;

--
-- Name: rate_limit_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.rate_limit_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    endpoint_path character varying(200) NOT NULL,
    http_method character varying(10) DEFAULT 'POST'::character varying NOT NULL,
    requests_per_minute integer DEFAULT 60 NOT NULL,
    burst_size integer DEFAULT 20 NOT NULL,
    algorithm character varying(20) DEFAULT 'token_bucket'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    updated_by character varying(100),
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.rate_limit_config OWNER TO uw_user;

--
-- Name: ri_cession_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.ri_cession_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.ri_cession_seq OWNER TO uw_user;

--
-- Name: ri_cession; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.ri_cession (
    id integer NOT NULL,
    cession_ref character varying(40) DEFAULT ((('RI-'::text || to_char(now(), 'YYYYMMDD'::text)) || '-'::text) || lpad((nextval('public.ri_cession_seq'::regclass))::text, 4, '0'::text)) NOT NULL,
    case_id character varying(40) NOT NULL,
    application_id character varying(40),
    reinsurer_id integer,
    treaty_code character varying(40),
    status character varying(30) DEFAULT 'PENDING_SUBMISSION'::character varying NOT NULL,
    cession_type character varying(20) DEFAULT 'FACULTATIVE'::character varying,
    gross_face_amount numeric(15,2),
    retention_amount numeric(15,2),
    ceded_amount numeric(15,2),
    gross_premium numeric(15,2),
    ri_premium numeric(15,2),
    net_retained_premium numeric(15,2),
    ri_decision character varying(20),
    ri_decision_date date,
    ri_modified_terms text,
    ri_reference character varying(100),
    slip_generated_at timestamp with time zone,
    submitted_at timestamp with time zone,
    decision_received_at timestamp with time zone,
    submitted_by character varying(100),
    cession_effective_date date,
    cession_expiry_date date,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.ri_cession OWNER TO uw_user;

--
-- Name: ri_cession_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.ri_cession_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.ri_cession_id_seq OWNER TO uw_user;

--
-- Name: ri_cession_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.ri_cession_id_seq OWNED BY public.ri_cession.id;


--
-- Name: ri_reinsurer; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.ri_reinsurer (
    id integer NOT NULL,
    reinsurer_code character varying(20) NOT NULL,
    reinsurer_name character varying(200) NOT NULL,
    treaty_code character varying(40),
    treaty_type character varying(20) DEFAULT 'FACULTATIVE'::character varying,
    contact_name character varying(200),
    contact_email character varying(200),
    retention_limit numeric(15,2),
    product_codes text[],
    currency character varying(10) DEFAULT 'INR'::character varying,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    treaty_effective_date date,
    treaty_expiry_date date
);


ALTER TABLE public.ri_reinsurer OWNER TO uw_user;

--
-- Name: ri_reinsurer_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.ri_reinsurer_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.ri_reinsurer_id_seq OWNER TO uw_user;

--
-- Name: ri_reinsurer_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.ri_reinsurer_id_seq OWNED BY public.ri_reinsurer.id;


--
-- Name: rule_approval; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.rule_approval (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    rule_id character varying(100) NOT NULL,
    action character varying(30) NOT NULL,
    actor character varying(100) NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.rule_approval OWNER TO uw_user;

--
-- Name: rule_custom_fields; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.rule_custom_fields (
    field_name character varying(80) NOT NULL,
    label character varying(120),
    data_type character varying(20) DEFAULT 'numeric'::character varying,
    description text,
    added_by character varying(80),
    added_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.rule_custom_fields OWNER TO uw_user;

--
-- Name: scheduled_batch_job; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.scheduled_batch_job (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    job_name character varying(200) NOT NULL,
    description text,
    cron_expression character varying(100),
    run_at_time time without time zone,
    run_on_days character varying(50),
    timezone character varying(50) DEFAULT 'UTC'::character varying,
    product_code character varying(20),
    dry_run boolean DEFAULT false,
    is_active boolean DEFAULT true,
    last_run_at timestamp without time zone,
    next_run_at timestamp without time zone,
    last_job_id uuid,
    last_status character varying(30),
    run_count integer DEFAULT 0,
    created_by character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.scheduled_batch_job OWNER TO uw_user;

--
-- Name: smtp_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.smtp_config (
    key character varying(40) NOT NULL,
    value text
);


ALTER TABLE public.smtp_config OWNER TO uw_user;

--
-- Name: state_codes; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.state_codes (
    id integer NOT NULL,
    country_code character varying(5) DEFAULT 'IN'::character varying NOT NULL,
    state_code character varying(10) NOT NULL,
    state_name character varying(100),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.state_codes OWNER TO uw_user;

--
-- Name: state_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.state_codes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.state_codes_id_seq OWNER TO uw_user;

--
-- Name: state_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.state_codes_id_seq OWNED BY public.state_codes.id;


--
-- Name: system_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.system_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    config_key character varying(100) NOT NULL,
    config_value text NOT NULL,
    config_type character varying(20) DEFAULT 'string'::character varying,
    description character varying(300),
    updated_by character varying(100),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.system_config OWNER TO uw_user;

--
-- Name: tenant; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.tenant (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_code character varying(30) NOT NULL,
    tenant_name character varying(200) NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying,
    plan_tier character varying(20) DEFAULT 'STANDARD'::character varying,
    contact_name character varying(100),
    contact_email character varying(200),
    contact_phone character varying(30),
    company_type character varying(50),
    state_of_domicile character varying(2),
    naic_code character varying(10),
    max_users integer DEFAULT 50,
    max_decisions_per_month integer DEFAULT 10000,
    decisions_this_month integer DEFAULT 0,
    decisions_reset_at timestamp without time zone,
    sso_enabled boolean DEFAULT false,
    sso_provider character varying(50),
    sso_config jsonb,
    api_enabled boolean DEFAULT true,
    api_key_hash character varying(200),
    logo_url character varying(500),
    timezone character varying(50) DEFAULT 'America/New_York'::character varying,
    date_format character varying(20) DEFAULT 'YYYY-MM-DD'::character varying,
    branding jsonb,
    allowed_ips jsonb,
    notes text,
    trial_ends_at timestamp without time zone,
    contract_start date,
    contract_end date,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    created_by character varying(100)
);


ALTER TABLE public.tenant OWNER TO uw_user;

--
-- Name: tenant_audit; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.tenant_audit (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    actor character varying(100),
    before_val jsonb,
    after_val jsonb,
    ip_address character varying(45),
    occurred_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.tenant_audit OWNER TO uw_user;

--
-- Name: tenant_rule_config; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.tenant_rule_config (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    rule_id character varying(100) NOT NULL,
    rule_name character varying(200),
    category character varying(50),
    is_enabled boolean DEFAULT true,
    points_override integer,
    threshold_override jsonb,
    notes text,
    updated_by character varying(100),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.tenant_rule_config OWNER TO uw_user;

--
-- Name: tenant_usage; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.tenant_usage (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    metric_date date NOT NULL,
    decisions_made integer DEFAULT 0,
    batch_jobs_run integer DEFAULT 0,
    api_calls integer DEFAULT 0,
    active_users integer DEFAULT 0
);


ALTER TABLE public.tenant_usage OWNER TO uw_user;

--
-- Name: user_authority_limits; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.user_authority_limits (
    id integer NOT NULL,
    username character varying(100) NOT NULL,
    min_face_amount numeric(15,2) DEFAULT 0 NOT NULL,
    max_face_amount numeric(15,2),
    product_codes text[],
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    set_by character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_medical_officer boolean DEFAULT false,
    medical_specialisations text[] DEFAULT '{}'::text[],
    can_assess_medical boolean DEFAULT false
);


ALTER TABLE public.user_authority_limits OWNER TO uw_user;

--
-- Name: COLUMN user_authority_limits.is_medical_officer; Type: COMMENT; Schema: public; Owner: uw_user
--

COMMENT ON COLUMN public.user_authority_limits.is_medical_officer IS 'TRUE if this underwriter is a qualified medical officer';


--
-- Name: COLUMN user_authority_limits.medical_specialisations; Type: COMMENT; Schema: public; Owner: uw_user
--

COMMENT ON COLUMN public.user_authority_limits.medical_specialisations IS 'List of medical specialisations e.g. {Cardiology,Oncology}';


--
-- Name: COLUMN user_authority_limits.can_assess_medical; Type: COMMENT; Schema: public; Owner: uw_user
--

COMMENT ON COLUMN public.user_authority_limits.can_assess_medical IS 'TRUE if user can make medical assessments without referral';


--
-- Name: user_authority_limits_id_seq; Type: SEQUENCE; Schema: public; Owner: uw_user
--

CREATE SEQUENCE public.user_authority_limits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.user_authority_limits_id_seq OWNER TO uw_user;

--
-- Name: user_authority_limits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: uw_user
--

ALTER SEQUENCE public.user_authority_limits_id_seq OWNED BY public.user_authority_limits.id;


--
-- Name: uw_case; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.uw_case (
    case_number character varying(30) NOT NULL,
    application_id uuid NOT NULL,
    product_type character varying(30) NOT NULL,
    status character varying(30) NOT NULL,
    decision_pathway character varying(30),
    assigned_uw_id uuid,
    assigned_at timestamp with time zone,
    sla_due_at timestamp with time zone,
    sla_breached boolean NOT NULL,
    priority_score smallint,
    complexity_score smallint,
    auto_decision_at timestamp with time zone,
    final_decision_at timestamp with time zone,
    decision_cycle_ms bigint,
    reinsurance_required boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) NOT NULL,
    updated_by character varying(100) NOT NULL,
    version bigint NOT NULL,
    is_deleted boolean NOT NULL,
    tenant_id uuid NOT NULL,
    uw_notes text,
    product_code character varying(20),
    applicant_age smallint,
    face_amount numeric(15,2),
    CONSTRAINT chk_case_pathway CHECK ((((decision_pathway)::text = ANY ((ARRAY['STRAIGHT_THROUGH'::character varying, 'ACCELERATED'::character varying, 'REFERRED'::character varying, 'INSTANT_DECLINE'::character varying])::text[])) OR (decision_pathway IS NULL))),
    CONSTRAINT chk_case_status CHECK (((status)::text = ANY ((ARRAY['OPEN'::character varying, 'IN_PROGRESS'::character varying, 'PENDING_DATA'::character varying, 'PENDING_REQUIREMENTS'::character varying, 'PENDING_REVIEW'::character varying, 'APPROVED'::character varying, 'DECLINED'::character varying, 'CLOSED'::character varying, 'CANCELLED'::character varying])::text[])))
);


ALTER TABLE public.uw_case OWNER TO uw_user;

--
-- Name: uw_decision; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.uw_decision (
    case_id uuid NOT NULL,
    application_id uuid NOT NULL,
    decision_sequence smallint NOT NULL,
    is_final boolean NOT NULL,
    outcome character varying(40) NOT NULL,
    risk_class character varying(30),
    table_rating smallint,
    table_pct smallint,
    flat_extra_per_thou numeric(8,4),
    flat_extra_years smallint,
    total_debit_points smallint NOT NULL,
    total_credit_points smallint NOT NULL,
    net_debit_points smallint NOT NULL,
    approved_face_amount numeric(15,2),
    approved_premium numeric(12,4),
    decline_reason_code character varying(50),
    adverse_action_text text,
    postpone_until date,
    conditions_json jsonb,
    exclusions_json jsonb,
    findings_json jsonb NOT NULL,
    is_override boolean NOT NULL,
    override_reason text,
    decided_by_type character varying(20) NOT NULL,
    decided_by_id uuid,
    decided_at timestamp with time zone DEFAULT now(),
    decision_rules_ver character varying(30),
    decision_model_ver character varying(30),
    primary_reason text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) NOT NULL,
    updated_by character varying(100) NOT NULL,
    version bigint NOT NULL,
    is_deleted boolean NOT NULL,
    tenant_id uuid NOT NULL,
    CONSTRAINT chk_decision_by_type CHECK (((decided_by_type)::text = ANY ((ARRAY['AUTOMATED'::character varying, 'UNDERWRITER'::character varying, 'SUPERVISOR'::character varying])::text[])))
);


ALTER TABLE public.uw_decision OWNER TO uw_user;

--
-- Name: uw_user; Type: TABLE; Schema: public; Owner: uw_user
--

CREATE TABLE public.uw_user (
    username character varying(100) NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255),
    full_name character varying(255),
    role character varying(30) NOT NULL,
    is_active boolean NOT NULL,
    last_login_at timestamp with time zone,
    api_key_hash character varying(64),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by character varying(100) NOT NULL,
    updated_by character varying(100) NOT NULL,
    version bigint NOT NULL,
    is_deleted boolean NOT NULL,
    tenant_id uuid NOT NULL,
    effective_date date,
    expiry_date date,
    CONSTRAINT chk_user_role CHECK (((role)::text = ANY ((ARRAY['super_admin'::character varying, 'admin'::character varying, 'senior_underwriter'::character varying, 'underwriter'::character varying, 'api_client'::character varying, 'readonly'::character varying])::text[])))
);


ALTER TABLE public.uw_user OWNER TO uw_user;

--
-- Name: applicant_master id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.applicant_master ALTER COLUMN id SET DEFAULT nextval('public.applicant_master_id_seq'::regclass);


--
-- Name: audit_trail id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.audit_trail ALTER COLUMN id SET DEFAULT nextval('public.audit_trail_id_seq'::regclass);


--
-- Name: batch_job_records id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_job_records ALTER COLUMN id SET DEFAULT nextval('public.batch_job_records_id_seq'::regclass);


--
-- Name: batch_recurring_schedules id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_recurring_schedules ALTER COLUMN id SET DEFAULT nextval('public.batch_recurring_schedules_id_seq'::regclass);


--
-- Name: batch_scheduled_jobs id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_scheduled_jobs ALTER COLUMN id SET DEFAULT nextval('public.batch_scheduled_jobs_id_seq'::regclass);


--
-- Name: error_codes id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_codes ALTER COLUMN id SET DEFAULT nextval('public.error_codes_id_seq'::regclass);


--
-- Name: member_upload_log id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.member_upload_log ALTER COLUMN id SET DEFAULT nextval('public.member_upload_log_id_seq'::regclass);


--
-- Name: notification_log id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.notification_log ALTER COLUMN id SET DEFAULT nextval('public.notification_log_id_seq'::regclass);


--
-- Name: physicians id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.physicians ALTER COLUMN id SET DEFAULT nextval('public.physicians_id_seq'::regclass);


--
-- Name: policy_admin_queue id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.policy_admin_queue ALTER COLUMN id SET DEFAULT nextval('public.policy_admin_queue_id_seq'::regclass);


--
-- Name: product_build_table id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_build_table ALTER COLUMN id SET DEFAULT nextval('public.product_build_table_id_seq'::regclass);


--
-- Name: product_rules id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rules ALTER COLUMN id SET DEFAULT nextval('public.product_rules_id_seq'::regclass);


--
-- Name: ri_cession id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_cession ALTER COLUMN id SET DEFAULT nextval('public.ri_cession_id_seq'::regclass);


--
-- Name: ri_reinsurer id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_reinsurer ALTER COLUMN id SET DEFAULT nextval('public.ri_reinsurer_id_seq'::regclass);


--
-- Name: state_codes id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.state_codes ALTER COLUMN id SET DEFAULT nextval('public.state_codes_id_seq'::regclass);


--
-- Name: user_authority_limits id; Type: DEFAULT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.user_authority_limits ALTER COLUMN id SET DEFAULT nextval('public.user_authority_limits_id_seq'::regclass);


--
-- Name: applicant_master applicant_master_applicant_ref_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.applicant_master
    ADD CONSTRAINT applicant_master_applicant_ref_key UNIQUE (applicant_ref);


--
-- Name: applicant_master applicant_master_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.applicant_master
    ADD CONSTRAINT applicant_master_pkey PRIMARY KEY (id);


--
-- Name: application application_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.application
    ADD CONSTRAINT application_pkey PRIMARY KEY (id);


--
-- Name: aps_letter_templates aps_letter_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.aps_letter_templates
    ADD CONSTRAINT aps_letter_templates_pkey PRIMARY KEY (id);


--
-- Name: aps_request aps_request_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.aps_request
    ADD CONSTRAINT aps_request_pkey PRIMARY KEY (id);


--
-- Name: audit_event audit_event_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.audit_event
    ADD CONSTRAINT audit_event_pkey PRIMARY KEY (id);


--
-- Name: audit_trail audit_trail_event_id_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.audit_trail
    ADD CONSTRAINT audit_trail_event_id_key UNIQUE (event_id);


--
-- Name: audit_trail audit_trail_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.audit_trail
    ADD CONSTRAINT audit_trail_pkey PRIMARY KEY (id);


--
-- Name: batch_job batch_job_job_number_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_job
    ADD CONSTRAINT batch_job_job_number_key UNIQUE (job_number);


--
-- Name: batch_job batch_job_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_job
    ADD CONSTRAINT batch_job_pkey PRIMARY KEY (id);


--
-- Name: batch_job_records batch_job_records_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_job_records
    ADD CONSTRAINT batch_job_records_pkey PRIMARY KEY (id);


--
-- Name: batch_jobs batch_jobs_job_number_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_jobs
    ADD CONSTRAINT batch_jobs_job_number_key UNIQUE (job_number);


--
-- Name: batch_jobs batch_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_jobs
    ADD CONSTRAINT batch_jobs_pkey PRIMARY KEY (id);


--
-- Name: batch_record batch_record_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_record
    ADD CONSTRAINT batch_record_pkey PRIMARY KEY (id);


--
-- Name: batch_recurring_schedules batch_recurring_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_recurring_schedules
    ADD CONSTRAINT batch_recurring_schedules_pkey PRIMARY KEY (id);


--
-- Name: batch_scheduled_jobs batch_scheduled_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_scheduled_jobs
    ADD CONSTRAINT batch_scheduled_jobs_pkey PRIMARY KEY (id);


--
-- Name: custom_rule_history custom_rule_history_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.custom_rule_history
    ADD CONSTRAINT custom_rule_history_pkey PRIMARY KEY (id);


--
-- Name: custom_uw_rule custom_uw_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.custom_uw_rule
    ADD CONSTRAINT custom_uw_rule_pkey PRIMARY KEY (id);


--
-- Name: error_code error_code_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_code
    ADD CONSTRAINT error_code_pkey PRIMARY KEY (id);


--
-- Name: error_code error_code_tenant_id_error_number_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_code
    ADD CONSTRAINT error_code_tenant_id_error_number_key UNIQUE (tenant_id, error_number);


--
-- Name: error_codes error_codes_error_code_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_codes
    ADD CONSTRAINT error_codes_error_code_key UNIQUE (error_code);


--
-- Name: error_codes error_codes_error_number_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_codes
    ADD CONSTRAINT error_codes_error_number_key UNIQUE (error_number);


--
-- Name: error_codes error_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.error_codes
    ADD CONSTRAINT error_codes_pkey PRIMARY KEY (id);


--
-- Name: letter_template letter_template_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.letter_template
    ADD CONSTRAINT letter_template_pkey PRIMARY KEY (id);


--
-- Name: letter_templates letter_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.letter_templates
    ADD CONSTRAINT letter_templates_pkey PRIMARY KEY (id);


--
-- Name: login_attempts login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.login_attempts
    ADD CONSTRAINT login_attempts_pkey PRIMARY KEY (username);


--
-- Name: member_upload_log member_upload_log_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.member_upload_log
    ADD CONSTRAINT member_upload_log_pkey PRIMARY KEY (id);


--
-- Name: mfa_config mfa_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.mfa_config
    ADD CONSTRAINT mfa_config_pkey PRIMARY KEY (username);


--
-- Name: notification_config notification_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.notification_config
    ADD CONSTRAINT notification_config_pkey PRIMARY KEY (event);


--
-- Name: notification_log notification_log_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.notification_log
    ADD CONSTRAINT notification_log_pkey PRIMARY KEY (id);


--
-- Name: output_interface_config output_interface_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.output_interface_config
    ADD CONSTRAINT output_interface_config_pkey PRIMARY KEY (key);


--
-- Name: physicians physicians_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.physicians
    ADD CONSTRAINT physicians_pkey PRIMARY KEY (id);


--
-- Name: policy_admin_queue policy_admin_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.policy_admin_queue
    ADD CONSTRAINT policy_admin_queue_pkey PRIMARY KEY (id);


--
-- Name: premium_rate_table premium_rate_table_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.premium_rate_table
    ADD CONSTRAINT premium_rate_table_pkey PRIMARY KEY (id);


--
-- Name: product_build_table product_build_table_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_build_table
    ADD CONSTRAINT product_build_table_pkey PRIMARY KEY (id);


--
-- Name: product_build_table product_build_table_product_code_bmi_min_bmi_max_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_build_table
    ADD CONSTRAINT product_build_table_product_code_bmi_min_bmi_max_key UNIQUE (product_code, bmi_min, bmi_max);


--
-- Name: product_build_tables product_build_tables_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_build_tables
    ADD CONSTRAINT product_build_tables_pkey PRIMARY KEY (id);


--
-- Name: product_decision_thresholds product_decision_thresholds_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_decision_thresholds
    ADD CONSTRAINT product_decision_thresholds_pkey PRIMARY KEY (id);


--
-- Name: product product_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product
    ADD CONSTRAINT product_pkey PRIMARY KEY (id);


--
-- Name: product_rule_config_audit product_rule_config_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rule_config_audit
    ADD CONSTRAINT product_rule_config_audit_pkey PRIMARY KEY (id);


--
-- Name: product_rule_configs product_rule_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rule_configs
    ADD CONSTRAINT product_rule_configs_pkey PRIMARY KEY (id);


--
-- Name: product_rules product_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rules
    ADD CONSTRAINT product_rules_pkey PRIMARY KEY (id);


--
-- Name: product_rules product_rules_product_code_rule_id_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rules
    ADD CONSTRAINT product_rules_product_code_rule_id_key UNIQUE (product_code, rule_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (product_code);


--
-- Name: rate_limit_config rate_limit_config_endpoint_path_http_method_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.rate_limit_config
    ADD CONSTRAINT rate_limit_config_endpoint_path_http_method_key UNIQUE (endpoint_path, http_method);


--
-- Name: rate_limit_config rate_limit_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.rate_limit_config
    ADD CONSTRAINT rate_limit_config_pkey PRIMARY KEY (id);


--
-- Name: ri_cession ri_cession_cession_ref_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_cession
    ADD CONSTRAINT ri_cession_cession_ref_key UNIQUE (cession_ref);


--
-- Name: ri_cession ri_cession_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_cession
    ADD CONSTRAINT ri_cession_pkey PRIMARY KEY (id);


--
-- Name: ri_reinsurer ri_reinsurer_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_reinsurer
    ADD CONSTRAINT ri_reinsurer_pkey PRIMARY KEY (id);


--
-- Name: ri_reinsurer ri_reinsurer_reinsurer_code_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_reinsurer
    ADD CONSTRAINT ri_reinsurer_reinsurer_code_key UNIQUE (reinsurer_code);


--
-- Name: rule_approval rule_approval_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.rule_approval
    ADD CONSTRAINT rule_approval_pkey PRIMARY KEY (id);


--
-- Name: rule_custom_fields rule_custom_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.rule_custom_fields
    ADD CONSTRAINT rule_custom_fields_pkey PRIMARY KEY (field_name);


--
-- Name: scheduled_batch_job scheduled_batch_job_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.scheduled_batch_job
    ADD CONSTRAINT scheduled_batch_job_pkey PRIMARY KEY (id);


--
-- Name: smtp_config smtp_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.smtp_config
    ADD CONSTRAINT smtp_config_pkey PRIMARY KEY (key);


--
-- Name: state_codes state_codes_country_code_state_code_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.state_codes
    ADD CONSTRAINT state_codes_country_code_state_code_key UNIQUE (country_code, state_code);


--
-- Name: state_codes state_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.state_codes
    ADD CONSTRAINT state_codes_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_tenant_id_config_key_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_tenant_id_config_key_key UNIQUE (tenant_id, config_key);


--
-- Name: tenant_audit tenant_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant_audit
    ADD CONSTRAINT tenant_audit_pkey PRIMARY KEY (id);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (id);


--
-- Name: tenant_rule_config tenant_rule_config_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant_rule_config
    ADD CONSTRAINT tenant_rule_config_pkey PRIMARY KEY (id);


--
-- Name: tenant_rule_config tenant_rule_config_tenant_id_rule_id_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant_rule_config
    ADD CONSTRAINT tenant_rule_config_tenant_id_rule_id_key UNIQUE (tenant_id, rule_id);


--
-- Name: tenant tenant_tenant_code_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_tenant_code_key UNIQUE (tenant_code);


--
-- Name: tenant_usage tenant_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant_usage
    ADD CONSTRAINT tenant_usage_pkey PRIMARY KEY (id);


--
-- Name: tenant_usage tenant_usage_tenant_id_metric_date_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.tenant_usage
    ADD CONSTRAINT tenant_usage_tenant_id_metric_date_key UNIQUE (tenant_id, metric_date);


--
-- Name: application uq_application_number; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.application
    ADD CONSTRAINT uq_application_number UNIQUE (tenant_id, application_number);


--
-- Name: uw_case uq_case_number; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_case
    ADD CONSTRAINT uq_case_number UNIQUE (tenant_id, case_number);


--
-- Name: custom_uw_rule uq_custom_uw_rule; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.custom_uw_rule
    ADD CONSTRAINT uq_custom_uw_rule UNIQUE (tenant_id, rule_id);


--
-- Name: letter_template uq_letter_template; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.letter_template
    ADD CONSTRAINT uq_letter_template UNIQUE (tenant_id, outcome, template_name);


--
-- Name: product_decision_thresholds uq_product_decision_threshold; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_decision_thresholds
    ADD CONSTRAINT uq_product_decision_threshold UNIQUE (tenant_id, product_code);


--
-- Name: product_rule_configs uq_product_rule_config; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product_rule_configs
    ADD CONSTRAINT uq_product_rule_config UNIQUE (tenant_id, product_code, rule_id);


--
-- Name: product uq_product_tenant_code; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.product
    ADD CONSTRAINT uq_product_tenant_code UNIQUE (tenant_id, product_code);


--
-- Name: uw_user uq_user_email; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_user
    ADD CONSTRAINT uq_user_email UNIQUE (tenant_id, email);


--
-- Name: uw_user uq_user_username; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_user
    ADD CONSTRAINT uq_user_username UNIQUE (tenant_id, username);


--
-- Name: user_authority_limits user_authority_limits_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.user_authority_limits
    ADD CONSTRAINT user_authority_limits_pkey PRIMARY KEY (id);


--
-- Name: user_authority_limits user_authority_limits_username_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.user_authority_limits
    ADD CONSTRAINT user_authority_limits_username_key UNIQUE (username);


--
-- Name: uw_case uw_case_application_id_key; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_case
    ADD CONSTRAINT uw_case_application_id_key UNIQUE (application_id);


--
-- Name: uw_case uw_case_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_case
    ADD CONSTRAINT uw_case_pkey PRIMARY KEY (id);


--
-- Name: uw_decision uw_decision_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_decision
    ADD CONSTRAINT uw_decision_pkey PRIMARY KEY (id);


--
-- Name: uw_user uw_user_pkey; Type: CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_user
    ADD CONSTRAINT uw_user_pkey PRIMARY KEY (id);


--
-- Name: idx_applicant_master_email; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_applicant_master_email ON public.applicant_master USING btree (email);


--
-- Name: idx_applicant_master_ref; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_applicant_master_ref ON public.applicant_master USING btree (applicant_ref);


--
-- Name: idx_application_product; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_application_product ON public.application USING btree (product_type);


--
-- Name: idx_application_submitted_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_application_submitted_at ON public.application USING btree (submitted_at);


--
-- Name: idx_application_tenant_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_application_tenant_status ON public.application USING btree (tenant_id, status);


--
-- Name: idx_aps_case; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_aps_case ON public.aps_request USING btree (case_id);


--
-- Name: idx_audit_actor; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_actor ON public.audit_event USING btree (actor_id, occurred_at);


--
-- Name: idx_audit_category; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_category ON public.audit_trail USING btree (event_category, occurred_at DESC);


--
-- Name: idx_audit_entity; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_entity ON public.audit_event USING btree (entity_type, entity_id, occurred_at);


--
-- Name: idx_audit_occurred; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_occurred ON public.audit_trail USING btree (occurred_at DESC);


--
-- Name: idx_audit_tenant; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_tenant ON public.audit_event USING btree (tenant_id, occurred_at);


--
-- Name: idx_audit_type; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_audit_type ON public.audit_event USING btree (event_type, occurred_at);


--
-- Name: idx_batch_job_records_applicant_ref; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_job_records_applicant_ref ON public.batch_job_records USING btree (applicant_ref);


--
-- Name: idx_batch_job_records_job_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_job_records_job_id ON public.batch_job_records USING btree (job_id);


--
-- Name: idx_batch_job_records_outcome; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_job_records_outcome ON public.batch_job_records USING btree (outcome);


--
-- Name: idx_batch_jobs_completed_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_jobs_completed_at ON public.batch_jobs USING btree (completed_at DESC);


--
-- Name: idx_batch_jobs_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_jobs_status ON public.batch_jobs USING btree (status);


--
-- Name: idx_batch_record_job; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_batch_record_job ON public.batch_record USING btree (job_id);


--
-- Name: idx_case_assigned_uw; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_case_assigned_uw ON public.uw_case USING btree (assigned_uw_id);


--
-- Name: idx_case_sla_due; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_case_sla_due ON public.uw_case USING btree (sla_due_at);


--
-- Name: idx_case_tenant_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_case_tenant_status ON public.uw_case USING btree (tenant_id, status);


--
-- Name: idx_custom_uw_rule_tenant_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_custom_uw_rule_tenant_status ON public.custom_uw_rule USING btree (tenant_id, status) WHERE (is_deleted = false);


--
-- Name: idx_decision_case; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_decision_case ON public.uw_decision USING btree (case_id);


--
-- Name: idx_decision_final; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_decision_final ON public.uw_decision USING btree (case_id) WHERE (is_final = true);


--
-- Name: idx_decision_outcome; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_decision_outcome ON public.uw_decision USING btree (outcome, decided_at);


--
-- Name: idx_decision_override; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_decision_override ON public.uw_decision USING btree (is_override) WHERE (is_override = true);


--
-- Name: idx_paq_applicant_ref; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_paq_applicant_ref ON public.policy_admin_queue USING btree (applicant_ref);


--
-- Name: idx_paq_created_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_paq_created_at ON public.policy_admin_queue USING btree (created_at);


--
-- Name: idx_paq_push_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_paq_push_status ON public.policy_admin_queue USING btree (push_status) WHERE ((push_status)::text = 'PENDING'::text);


--
-- Name: idx_paq_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_paq_status ON public.policy_admin_queue USING btree (status);


--
-- Name: idx_products_active; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_products_active ON public.products USING btree (is_active);


--
-- Name: idx_products_type; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_products_type ON public.products USING btree (product_type);


--
-- Name: idx_rate_lookup; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_rate_lookup ON public.premium_rate_table USING btree (product_code, gender, age_min, age_max);


--
-- Name: idx_rate_tenant_lookup; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_rate_tenant_lookup ON public.premium_rate_table USING btree (tenant_id, product_code, gender, age_min, age_max);


--
-- Name: idx_ri_cession_case; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_ri_cession_case ON public.ri_cession USING btree (case_id);


--
-- Name: idx_ri_cession_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_ri_cession_status ON public.ri_cession USING btree (status);


--
-- Name: idx_scheduled_batch_next_run; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_scheduled_batch_next_run ON public.scheduled_batch_job USING btree (next_run_at, is_active);


--
-- Name: idx_scheduled_batch_tenant; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_scheduled_batch_tenant ON public.scheduled_batch_job USING btree (tenant_id, is_active);


--
-- Name: idx_tenant_audit; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_tenant_audit ON public.tenant_audit USING btree (tenant_id, occurred_at);


--
-- Name: idx_tenant_code; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_tenant_code ON public.tenant USING btree (tenant_code);


--
-- Name: idx_tenant_rule; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_tenant_rule ON public.tenant_rule_config USING btree (tenant_id, rule_id);


--
-- Name: idx_tenant_usage; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_tenant_usage ON public.tenant_usage USING btree (tenant_id, metric_date);


--
-- Name: idx_user_tenant_active; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_user_tenant_active ON public.uw_user USING btree (tenant_id, is_active);


--
-- Name: idx_uw_case_assigned; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_uw_case_assigned ON public.uw_case USING btree (assigned_uw_id) WHERE (assigned_uw_id IS NOT NULL);


--
-- Name: idx_uw_case_status_tenant; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX idx_uw_case_status_tenant ON public.uw_case USING btree (tenant_id, status) WHERE ((status)::text = ANY ((ARRAY['OPEN'::character varying, 'REFERRED'::character varying, 'PENDING'::character varying])::text[]));


--
-- Name: ix_audit_changed_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_changed_at ON public.product_rule_config_audit USING btree (changed_at);


--
-- Name: ix_audit_tenant_product; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_tenant_product ON public.product_rule_config_audit USING btree (tenant_id, product_code);


--
-- Name: ix_audit_trail_actor_username; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_trail_actor_username ON public.audit_trail USING btree (actor_username);


--
-- Name: ix_audit_trail_entity_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_trail_entity_id ON public.audit_trail USING btree (entity_id);


--
-- Name: ix_audit_trail_event_category; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_trail_event_category ON public.audit_trail USING btree (event_category);


--
-- Name: ix_audit_trail_occurred_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_audit_trail_occurred_at ON public.audit_trail USING btree (occurred_at DESC);


--
-- Name: ix_batch_job_records_job_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_batch_job_records_job_id ON public.batch_job_records USING btree (job_id);


--
-- Name: ix_batch_jobs_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_batch_jobs_status ON public.batch_jobs USING btree (status);


--
-- Name: ix_batch_jobs_submitted_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_batch_jobs_submitted_at ON public.batch_jobs USING btree (submitted_at DESC);


--
-- Name: ix_notification_log_sent_at; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_notification_log_sent_at ON public.notification_log USING btree (sent_at DESC);


--
-- Name: ix_pbt_tenant_product; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_pbt_tenant_product ON public.product_build_tables USING btree (tenant_id, product_code);


--
-- Name: ix_policy_admin_queue_case_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_policy_admin_queue_case_id ON public.policy_admin_queue USING btree (case_id);


--
-- Name: ix_policy_admin_queue_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_policy_admin_queue_status ON public.policy_admin_queue USING btree (status);


--
-- Name: ix_prc_tenant_product; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_prc_tenant_product ON public.product_rule_configs USING btree (tenant_id, product_code);


--
-- Name: ix_product_build_tables_product_code; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_build_tables_product_code ON public.product_build_tables USING btree (product_code);


--
-- Name: ix_product_build_tables_tenant_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_build_tables_tenant_id ON public.product_build_tables USING btree (tenant_id);


--
-- Name: ix_product_decision_thresholds_product_code; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_decision_thresholds_product_code ON public.product_decision_thresholds USING btree (product_code);


--
-- Name: ix_product_decision_thresholds_tenant_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_decision_thresholds_tenant_id ON public.product_decision_thresholds USING btree (tenant_id);


--
-- Name: ix_product_rule_config_audit_tenant_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_rule_config_audit_tenant_id ON public.product_rule_config_audit USING btree (tenant_id);


--
-- Name: ix_product_rule_configs_product_code; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_rule_configs_product_code ON public.product_rule_configs USING btree (product_code);


--
-- Name: ix_product_rule_configs_rule_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_rule_configs_rule_id ON public.product_rule_configs USING btree (rule_id);


--
-- Name: ix_product_rule_configs_tenant_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_product_rule_configs_tenant_id ON public.product_rule_configs USING btree (tenant_id);


--
-- Name: ix_ri_cession_case_id; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_ri_cession_case_id ON public.ri_cession USING btree (case_id);


--
-- Name: ix_ri_cession_status; Type: INDEX; Schema: public; Owner: uw_user
--

CREATE INDEX ix_ri_cession_status ON public.ri_cession USING btree (status);


--
-- Name: audit_trail trg_audit_immutable; Type: TRIGGER; Schema: public; Owner: uw_user
--

CREATE TRIGGER trg_audit_immutable BEFORE DELETE OR UPDATE ON public.audit_trail FOR EACH ROW EXECUTE FUNCTION public.audit_trail_immutable();


--
-- Name: batch_job_records batch_job_records_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.batch_job_records
    ADD CONSTRAINT batch_job_records_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.batch_jobs(id) ON DELETE CASCADE;


--
-- Name: ri_cession ri_cession_reinsurer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.ri_cession
    ADD CONSTRAINT ri_cession_reinsurer_id_fkey FOREIGN KEY (reinsurer_id) REFERENCES public.ri_reinsurer(id);


--
-- Name: uw_case uw_case_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_case
    ADD CONSTRAINT uw_case_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.application(id);


--
-- Name: uw_case uw_case_assigned_uw_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_case
    ADD CONSTRAINT uw_case_assigned_uw_id_fkey FOREIGN KEY (assigned_uw_id) REFERENCES public.uw_user(id);


--
-- Name: uw_decision uw_decision_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_decision
    ADD CONSTRAINT uw_decision_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.application(id);


--
-- Name: uw_decision uw_decision_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: uw_user
--

ALTER TABLE ONLY public.uw_decision
    ADD CONSTRAINT uw_decision_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.uw_case(id);


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

GRANT ALL ON SCHEMA public TO uw_user;


--
-- PostgreSQL database dump complete
--


