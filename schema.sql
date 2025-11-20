

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


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "extensions";






CREATE TYPE "public"."app_role" AS ENUM (
    'admin',
    'member'
);


ALTER TYPE "public"."app_role" OWNER TO "postgres";


CREATE TYPE "public"."conversation_status" AS ENUM (
    'ongoing',
    'resolved_ai',
    'resolved_human',
    'escalated'
);


ALTER TYPE "public"."conversation_status" OWNER TO "postgres";


CREATE TYPE "public"."message_sender" AS ENUM (
    'user',
    'ai'
);


ALTER TYPE "public"."message_sender" OWNER TO "postgres";


CREATE TYPE "public"."user_role" AS ENUM (
    'admin',
    'member'
);


ALTER TYPE "public"."user_role" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_otps"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    DELETE FROM public.otps
    WHERE expires_at < CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_otps"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_org_id"("user_id" "uuid") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    -- Disable RLS for this query to prevent recursion
    SET LOCAL row_security = off;
    RETURN (SELECT org_id FROM users WHERE id = user_id);
END;
$$;


ALTER FUNCTION "public"."get_user_org_id"("user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") RETURNS boolean
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_roles
    WHERE user_id = _user_id
      AND role = _role
  )
$$;


ALTER FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."match_documents"("query_embedding" "extensions"."vector", "match_count" integer, "filter" "jsonb" DEFAULT '{}'::"jsonb") RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "embedding" "extensions"."vector", "similarity" double precision)
    LANGUAGE "plpgsql"
    SET "search_path" TO ''
    AS $$
BEGIN
  RETURN QUERY
  SELECT
    kb.id,
    kb.content,
    kb.metadata,
    kb.embedding,
    (1 - (kb.embedding <=> query_embedding))::float AS similarity
  FROM public.kb
  WHERE filter IS NULL OR kb.metadata @> filter
  ORDER BY kb.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;


ALTER FUNCTION "public"."match_documents"("query_embedding" "extensions"."vector", "match_count" integer, "filter" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."match_documents"("query_embedding" "extensions"."vector", "kb_id" "uuid", "match_count" integer DEFAULT 5) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "similarity" double precision)
    LANGUAGE "plpgsql"
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM documents d
    WHERE d.kb_id = match_documents.kb_id
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


ALTER FUNCTION "public"."match_documents"("query_embedding" "extensions"."vector", "kb_id" "uuid", "match_count" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."reset_messages_if_new_day"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    -- Check if the date has changed implying a new day has started
    IF NEW.date != OLD.date THEN
        NEW.messages_sent = 0;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."reset_messages_if_new_day"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."security_health_check"() RETURNS TABLE("table_name" "text", "issue_type" "text", "description" "text", "severity" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
  -- Check for tables without RLS
  RETURN QUERY
  SELECT 
    t.tablename::text,
    'Missing RLS'::text,
    'Table does not have Row Level Security enabled'::text,
    'HIGH'::text
  FROM pg_tables t
  LEFT JOIN pg_class c ON c.relname = t.tablename
  WHERE t.schemaname = 'public' 
    AND NOT c.relrowsecurity
    AND t.tablename NOT LIKE 'pg_%';
    
  -- Check for overly permissive policies
  RETURN QUERY
  SELECT 
    p.tablename::text,
    'Permissive Policy'::text,
    ('Policy "' || p.policyname || '" allows: ' || p.cmd)::text,
    'MEDIUM'::text
  FROM pg_policies p
  WHERE p.schemaname = 'public' 
    AND p.qual = 'true'
    AND p.cmd = 'SELECT';
END;
$$;


ALTER FUNCTION "public"."security_health_check"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."security_health_check"() IS 'Monitors database for common security misconfigurations';



CREATE OR REPLACE FUNCTION "public"."set_expiry"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
  -- Always set expires_at to 3 minutes after created_at
  NEW.expires_at := NEW.created_at + interval '3 minutes';
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_expiry"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_otp_expires_at"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
  NEW.expires_at := NEW.created_at + INTERVAL '5 minutes';
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_otp_expires_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO ''
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_updated_at_column"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."api_keys" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "org_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "api_key" "text",
    "key_hash" "text" NOT NULL,
    "permissions" "jsonb" DEFAULT '{"read": true, "admin": false, "write": true}'::"jsonb",
    "created_by" "uuid" NOT NULL,
    "last_used_at" timestamp with time zone,
    "expires_at" timestamp with time zone,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "shortcode" character varying(6) NOT NULL,
    "kb_id" "uuid" NOT NULL
);


ALTER TABLE "public"."api_keys" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."conversations" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "kb_id" "uuid" NOT NULL,
    "status" "public"."conversation_status" DEFAULT 'ongoing'::"public"."conversation_status",
    "started_at" timestamp with time zone DEFAULT "now"(),
    "resolved_at" timestamp with time zone,
    "escalation_status" "text" DEFAULT 'active',
    "customer_email" "text",
    "escalated_at" timestamp with time zone,
    "escalated_by" "text",
    "escalation_reason" "text"
);


ALTER TABLE "public"."conversations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."documents" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "kb_id" "uuid" NOT NULL,
    "file_id" "uuid",
    "content" "text" NOT NULL,
    "embedding" "extensions"."vector"(384),
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."files" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "kb_id" "uuid" NOT NULL,
    "filename" "text" NOT NULL,
    "file_path" "text",
    "url" "text",
    "file_type" "text" NOT NULL,
    "size_bytes" bigint,
    "uploaded_by" "uuid" NOT NULL,
    "uploaded_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."files" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."instances_duplicate" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "instance_name" "text" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "status" character varying(50) NOT NULL,
    "integration" character varying(255) NOT NULL,
    "settings" "jsonb" NOT NULL,
    "connected_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "timestamp" "date" DEFAULT CURRENT_DATE NOT NULL,
    "messages_sent" integer DEFAULT 0 NOT NULL,
    "api_key" character varying(255) NOT NULL,
    "webhook_id" "text",
    "webhook" "jsonb",
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "deleted_at" timestamp with time zone
);


ALTER TABLE "public"."instances_duplicate" OWNER TO "postgres";


COMMENT ON TABLE "public"."instances_duplicate" IS 'This is a duplicate of instances';



CREATE TABLE IF NOT EXISTS "public"."kb" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "content" "text" NOT NULL,
    "metadata" "jsonb" NOT NULL,
    "embedding" "extensions"."vector"(768) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."kb" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."knowledge_bases" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "org_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."knowledge_bases" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."messages" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "conv_id" "uuid" NOT NULL,
    "sender" "public"."message_sender" NOT NULL,
    "content" "text" NOT NULL,
    "timestamp" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."messages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."metrics" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "conv_id" "uuid" NOT NULL,
    "response_time" double precision,
    "resolution_time" double precision,
    "satisfaction_score" integer,
    "ai_responses" integer DEFAULT 0,
    "handoff_triggered" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "metrics_satisfaction_score_check" CHECK ((("satisfaction_score" >= 1) AND ("satisfaction_score" <= 5)))
);


ALTER TABLE "public"."metrics" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."organizations" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "name" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "description" "text",
    "team_size" integer,
    "support_email" "text"
);


ALTER TABLE "public"."organizations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_roles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "role" "public"."app_role" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."user_roles" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."users" (
    "id" "uuid" NOT NULL,
    "org_id" "uuid",
    "role" "public"."user_role" DEFAULT 'member'::"public"."user_role",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "email" "text",
    "first_name" "text",
    "last_name" "text"
);


ALTER TABLE "public"."users" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."users_duplicate" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "project_id" character varying(255) NOT NULL,
    "project_name" character varying(255),
    "api_key" character varying(255) NOT NULL,
    "email" character varying(255),
    "name" character varying(255),
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "deleted_at" timestamp with time zone
);


ALTER TABLE "public"."users_duplicate" OWNER TO "postgres";


COMMENT ON TABLE "public"."users_duplicate" IS 'This is a duplicate of users';



ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_key_hash_key" UNIQUE ("key_hash");



ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_shortcode_key" UNIQUE ("shortcode");



ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."instances_duplicate"
    ADD CONSTRAINT "instances_duplicate_instance_id_key" UNIQUE ("instance_name");



ALTER TABLE ONLY "public"."instances_duplicate"
    ADD CONSTRAINT "instances_duplicate_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."kb"
    ADD CONSTRAINT "kb_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."knowledge_bases"
    ADD CONSTRAINT "knowledge_bases_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."metrics"
    ADD CONSTRAINT "metrics_conv_id_key" UNIQUE ("conv_id");



ALTER TABLE ONLY "public"."metrics"
    ADD CONSTRAINT "metrics_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."organizations"
    ADD CONSTRAINT "organizations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_user_id_role_key" UNIQUE ("user_id", "role");



ALTER TABLE ONLY "public"."users_duplicate"
    ADD CONSTRAINT "users_duplicate_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."users_duplicate"
    ADD CONSTRAINT "users_duplicate_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."users_duplicate"
    ADD CONSTRAINT "users_duplicate_project_id_key" UNIQUE ("project_id");



ALTER TABLE ONLY "public"."users"
    ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");



CREATE INDEX "idx_api_keys_active" ON "public"."api_keys" USING "btree" ("is_active") WHERE ("is_active" = true);



CREATE INDEX "idx_api_keys_key_hash" ON "public"."api_keys" USING "btree" ("key_hash");



CREATE INDEX "idx_api_keys_org_id" ON "public"."api_keys" USING "btree" ("org_id");



CREATE INDEX "idx_api_keys_shortcode" ON "public"."api_keys" USING "btree" ("shortcode");



CREATE INDEX "idx_conversations_kb_id" ON "public"."conversations" USING "btree" ("kb_id");



CREATE INDEX "idx_conversations_user_id" ON "public"."conversations" USING "btree" ("user_id");



CREATE INDEX "idx_documents_embedding" ON "public"."documents" USING "ivfflat" ("embedding" "extensions"."vector_cosine_ops");



CREATE INDEX "idx_documents_file_id" ON "public"."documents" USING "btree" ("file_id");



CREATE INDEX "idx_documents_kb_id" ON "public"."documents" USING "btree" ("kb_id");



CREATE INDEX "idx_files_kb_id" ON "public"."files" USING "btree" ("kb_id");



CREATE INDEX "idx_kb_embedding" ON "public"."kb" USING "ivfflat" ("embedding" "extensions"."vector_cosine_ops") WITH ("lists"='100');



CREATE INDEX "idx_knowledge_bases_org_id" ON "public"."knowledge_bases" USING "btree" ("org_id");



CREATE INDEX "idx_messages_conv_id" ON "public"."messages" USING "btree" ("conv_id");



CREATE INDEX "idx_metrics_conv_id" ON "public"."metrics" USING "btree" ("conv_id");



CREATE INDEX "idx_users_org_id" ON "public"."users" USING "btree" ("org_id");



CREATE INDEX "instances_duplicate_status_idx" ON "public"."instances_duplicate" USING "btree" ("status");



CREATE INDEX "instances_duplicate_user_id_idx" ON "public"."instances_duplicate" USING "btree" ("user_id");



CREATE INDEX "users_duplicate_api_key_idx" ON "public"."users_duplicate" USING "btree" ("api_key");



CREATE INDEX "users_email_idx" ON "public"."users" USING "btree" ("email");



CREATE OR REPLACE TRIGGER "update_organizations_updated_at" BEFORE UPDATE ON "public"."organizations" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "public"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_kb_id_fkey" FOREIGN KEY ("kb_id") REFERENCES "public"."knowledge_bases"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_file_id_fkey" FOREIGN KEY ("file_id") REFERENCES "public"."files"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_kb_id_fkey" FOREIGN KEY ("kb_id") REFERENCES "public"."knowledge_bases"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_kb_id_fkey" FOREIGN KEY ("kb_id") REFERENCES "public"."knowledge_bases"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_uploaded_by_fkey" FOREIGN KEY ("uploaded_by") REFERENCES "public"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."knowledge_bases"
    ADD CONSTRAINT "knowledge_bases_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_conv_id_fkey" FOREIGN KEY ("conv_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."metrics"
    ADD CONSTRAINT "metrics_conv_id_fkey" FOREIGN KEY ("conv_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."user_roles"
    ADD CONSTRAINT "user_roles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."users"
    ADD CONSTRAINT "users_id_fkey" FOREIGN KEY ("id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."users"
    ADD CONSTRAINT "users_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;



ALTER TABLE "public"."api_keys" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "api_keys_delete" ON "public"."api_keys" FOR DELETE TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "api_keys_insert" ON "public"."api_keys" FOR INSERT TO "authenticated" WITH CHECK (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "api_keys_select" ON "public"."api_keys" FOR SELECT TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "api_keys_update" ON "public"."api_keys" FOR UPDATE TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



ALTER TABLE "public"."conversations" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "conversations_delete" ON "public"."conversations" FOR DELETE TO "authenticated" USING (("user_id" = ( SELECT "auth"."uid"() AS "uid")));



CREATE POLICY "conversations_insert" ON "public"."conversations" FOR INSERT TO "authenticated" WITH CHECK (("user_id" = ( SELECT "auth"."uid"() AS "uid")));



CREATE POLICY "conversations_select" ON "public"."conversations" FOR SELECT TO "authenticated" USING (("user_id" = ( SELECT "auth"."uid"() AS "uid")));



CREATE POLICY "conversations_update" ON "public"."conversations" FOR UPDATE TO "authenticated" USING (("user_id" = ( SELECT "auth"."uid"() AS "uid")));



ALTER TABLE "public"."documents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "documents_delete" ON "public"."documents" FOR DELETE TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "documents_insert" ON "public"."documents" FOR INSERT TO "authenticated" WITH CHECK (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "documents_select" ON "public"."documents" FOR SELECT TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "documents_update" ON "public"."documents" FOR UPDATE TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



ALTER TABLE "public"."files" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "files_delete" ON "public"."files" FOR DELETE TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "files_insert" ON "public"."files" FOR INSERT TO "authenticated" WITH CHECK (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "files_select" ON "public"."files" FOR SELECT TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



CREATE POLICY "files_update" ON "public"."files" FOR UPDATE TO "authenticated" USING (("kb_id" IN ( SELECT "knowledge_bases"."id"
   FROM "public"."knowledge_bases"
  WHERE ("knowledge_bases"."org_id" IN ( SELECT "users"."org_id"
           FROM "public"."users"
          WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))))));



ALTER TABLE "public"."instances_duplicate" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."kb" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "kb_insert" ON "public"."kb" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "kb_select" ON "public"."kb" FOR SELECT TO "authenticated" USING (true);



ALTER TABLE "public"."knowledge_bases" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "knowledge_bases_delete" ON "public"."knowledge_bases" FOR DELETE TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "knowledge_bases_insert" ON "public"."knowledge_bases" FOR INSERT TO "authenticated" WITH CHECK (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "knowledge_bases_select" ON "public"."knowledge_bases" FOR SELECT TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "knowledge_bases_service_insert" ON "public"."knowledge_bases" FOR INSERT TO "service_role" WITH CHECK (true);



CREATE POLICY "knowledge_bases_update" ON "public"."knowledge_bases" FOR UPDATE TO "authenticated" USING (("org_id" IN ( SELECT "users"."org_id"
   FROM "public"."users"
  WHERE ("users"."id" = ( SELECT "auth"."uid"() AS "uid")))));



ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "messages_delete" ON "public"."messages" FOR DELETE TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "messages_insert" ON "public"."messages" FOR INSERT TO "authenticated" WITH CHECK (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "messages_select" ON "public"."messages" FOR SELECT TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "messages_update" ON "public"."messages" FOR UPDATE TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



ALTER TABLE "public"."metrics" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "metrics_delete" ON "public"."metrics" FOR DELETE TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "metrics_insert" ON "public"."metrics" FOR INSERT TO "authenticated" WITH CHECK (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "metrics_select" ON "public"."metrics" FOR SELECT TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



CREATE POLICY "metrics_update" ON "public"."metrics" FOR UPDATE TO "authenticated" USING (("conv_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = ( SELECT "auth"."uid"() AS "uid")))));



ALTER TABLE "public"."organizations" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "organizations_insert" ON "public"."organizations" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "organizations_select" ON "public"."organizations" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "organizations_update" ON "public"."organizations" FOR UPDATE TO "authenticated" USING (true);



ALTER TABLE "public"."user_roles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "user_roles_select" ON "public"."user_roles" FOR SELECT TO "authenticated" USING (("user_id" = ( SELECT "auth"."uid"() AS "uid")));



ALTER TABLE "public"."users" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."users_duplicate" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "users_insert" ON "public"."users" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "users_select" ON "public"."users" FOR SELECT TO "authenticated" USING (("id" = ( SELECT "auth"."uid"() AS "uid")));



CREATE POLICY "users_update" ON "public"."users" FOR UPDATE TO "authenticated" USING (("id" = ( SELECT "auth"."uid"() AS "uid"))) WITH CHECK (("id" = ( SELECT "auth"."uid"() AS "uid")));





ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";















































































































































































































































































































































































































































































































GRANT ALL ON FUNCTION "public"."cleanup_expired_otps"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_otps"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_otps"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_org_id"("user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_org_id"("user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_org_id"("user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "anon";
GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_role"("_user_id" "uuid", "_role" "public"."app_role") TO "service_role";









GRANT ALL ON FUNCTION "public"."reset_messages_if_new_day"() TO "anon";
GRANT ALL ON FUNCTION "public"."reset_messages_if_new_day"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."reset_messages_if_new_day"() TO "service_role";



GRANT ALL ON FUNCTION "public"."security_health_check"() TO "anon";
GRANT ALL ON FUNCTION "public"."security_health_check"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."security_health_check"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_expiry"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_expiry"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_expiry"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_otp_expires_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_otp_expires_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_otp_expires_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "service_role";






























GRANT ALL ON TABLE "public"."api_keys" TO "anon";
GRANT ALL ON TABLE "public"."api_keys" TO "authenticated";
GRANT ALL ON TABLE "public"."api_keys" TO "service_role";



GRANT ALL ON TABLE "public"."conversations" TO "anon";
GRANT ALL ON TABLE "public"."conversations" TO "authenticated";
GRANT ALL ON TABLE "public"."conversations" TO "service_role";



GRANT ALL ON TABLE "public"."documents" TO "anon";
GRANT ALL ON TABLE "public"."documents" TO "authenticated";
GRANT ALL ON TABLE "public"."documents" TO "service_role";



GRANT ALL ON TABLE "public"."files" TO "anon";
GRANT ALL ON TABLE "public"."files" TO "authenticated";
GRANT ALL ON TABLE "public"."files" TO "service_role";



GRANT ALL ON TABLE "public"."instances_duplicate" TO "anon";
GRANT ALL ON TABLE "public"."instances_duplicate" TO "authenticated";
GRANT ALL ON TABLE "public"."instances_duplicate" TO "service_role";



GRANT ALL ON TABLE "public"."kb" TO "anon";
GRANT ALL ON TABLE "public"."kb" TO "authenticated";
GRANT ALL ON TABLE "public"."kb" TO "service_role";



GRANT ALL ON TABLE "public"."knowledge_bases" TO "anon";
GRANT ALL ON TABLE "public"."knowledge_bases" TO "authenticated";
GRANT ALL ON TABLE "public"."knowledge_bases" TO "service_role";



GRANT ALL ON TABLE "public"."messages" TO "anon";
GRANT ALL ON TABLE "public"."messages" TO "authenticated";
GRANT ALL ON TABLE "public"."messages" TO "service_role";



GRANT ALL ON TABLE "public"."metrics" TO "anon";
GRANT ALL ON TABLE "public"."metrics" TO "authenticated";
GRANT ALL ON TABLE "public"."metrics" TO "service_role";



GRANT ALL ON TABLE "public"."organizations" TO "anon";
GRANT ALL ON TABLE "public"."organizations" TO "authenticated";
GRANT ALL ON TABLE "public"."organizations" TO "service_role";



GRANT ALL ON TABLE "public"."user_roles" TO "anon";
GRANT ALL ON TABLE "public"."user_roles" TO "authenticated";
GRANT ALL ON TABLE "public"."user_roles" TO "service_role";



GRANT ALL ON TABLE "public"."users" TO "anon";
GRANT ALL ON TABLE "public"."users" TO "authenticated";
GRANT ALL ON TABLE "public"."users" TO "service_role";



GRANT ALL ON TABLE "public"."users_duplicate" TO "anon";
GRANT ALL ON TABLE "public"."users_duplicate" TO "authenticated";
GRANT ALL ON TABLE "public"."users_duplicate" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";



























-- HMAC trigger function for API keys
CREATE OR REPLACE FUNCTION public.api_keys_hash_trigger()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  secret text;
  computed text;
BEGIN
  -- secret should be set as a Postgres setting via ALTER DATABASE or set in environment; fallback to empty if not set
  -- Use current_setting to read a runtime setting 'app.hmac_secret'. Set it via: ALTER SYSTEM SET "app.hmac_secret" = 'your_secret'; SELECT pg_reload_conf();
  BEGIN
    secret := current_setting('app.hmac_secret');
  EXCEPTION WHEN others THEN
    secret := NULL;
  END;

  -- Only run when api_key provided and not empty
  IF NEW.api_key IS NOT NULL AND length(trim(NEW.api_key)) > 0 THEN
    IF secret IS NULL OR secret = '' THEN
      RAISE EXCEPTION 'HMAC secret app.hmac_secret is not set. Set it before inserting API keys.';
    END IF;

    -- Compute HMAC-SHA256, output as hex
    computed := encode(hmac(NEW.api_key::bytea, secret::bytea, 'sha256'), 'hex');

    NEW.key_hash := computed;
    -- optionally store partial masked key for debugging; here we nullify plain key to avoid storing it
    NEW.api_key := NULL;
  END IF;

  RETURN NEW;
END;
$$;

-- Create trigger to call the function on INSERT or UPDATE
DROP TRIGGER IF EXISTS api_keys_hash_trigger ON public.api_keys;
CREATE TRIGGER api_keys_hash_trigger
BEFORE INSERT OR UPDATE ON public.api_keys
FOR EACH ROW
EXECUTE FUNCTION public.api_keys_hash_trigger();

-- Create function to verify API key (returns key details if valid)
CREATE OR REPLACE FUNCTION public.verify_api_key(api_key text)
RETURNS TABLE(id uuid, org_id uuid, name text, permissions jsonb, expires_at timestamptz, is_active boolean, last_used_at timestamptz, kb_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  secret text;
  computed_hash text;
  key_id uuid;
BEGIN
  -- Get the secret
  BEGIN
    secret := current_setting('app.hmac_secret');
  EXCEPTION WHEN others THEN
    secret := NULL;
  END;

  IF secret IS NULL OR secret = '' THEN
    RAISE EXCEPTION 'HMAC secret app.hmac_secret is not set.';
  END IF;

  -- Compute the hash for the provided key
  computed_hash := encode(hmac(api_key::bytea, secret::bytea, 'sha256'), 'hex');

  -- Find the key and update last_used_at if valid
  SELECT ak.id INTO key_id
  FROM public.api_keys ak
  WHERE ak.key_hash = computed_hash
    AND ak.is_active = true
    AND (ak.expires_at IS NULL OR ak.expires_at > now())
  LIMIT 1;

  -- Update last_used_at if key found
  IF key_id IS NOT NULL THEN
    UPDATE public.api_keys SET last_used_at = now() WHERE id = key_id;
  END IF;

  -- Return matching row if valid
  RETURN QUERY
  SELECT ak.id, ak.org_id, ak.name, ak.permissions, ak.expires_at, ak.is_active, ak.last_used_at, ak.kb_id
  FROM public.api_keys ak
  WHERE ak.id = key_id;
END;
$$;

-- Create function to update last_used_at for a key
CREATE OR REPLACE FUNCTION public.update_key_last_used(key_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
   UPDATE public.api_keys
   SET last_used_at = now()
   WHERE id = key_id;
END;
$$;

-- Create match_documents function for vector similarity search
CREATE OR REPLACE FUNCTION public.match_documents(
    query_embedding vector(384),
    kb_id uuid,
    match_count integer DEFAULT 5
)
RETURNS TABLE(id uuid, content text, metadata jsonb, similarity float)
LANGUAGE sql
SECURITY DEFINER
AS $
    SELECT
        d.id,
        d.content,
        d.metadata,
        (1 - (d.embedding <=> query_embedding))::float AS similarity
    FROM documents d
    WHERE d.kb_id = match_documents.kb_id
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
$;

-- =============================================
-- PRODUCTION READINESS - DATABASE TRIGGERS
-- =============================================

-- Create audit log table
CREATE TABLE IF NOT EXISTS "public"."audit_logs" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "table_name" text NOT NULL,
    "record_id" uuid NOT NULL,
    "operation" text NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    "old_values" jsonb,
    "new_values" jsonb,
    "user_id" uuid,
    "org_id" uuid,
    "timestamp" timestamp with time zone DEFAULT "now"() NOT NULL,
    "ip_address" text,
    "user_agent" text
);

ALTER TABLE "public"."audit_logs" OWNER TO "postgres";

-- Create index for audit logs
CREATE INDEX IF NOT EXISTS "idx_audit_logs_table_record" ON "public"."audit_logs" USING "btree" ("table_name", "record_id");
CREATE INDEX IF NOT EXISTS "idx_audit_logs_timestamp" ON "public"."audit_logs" USING "btree" ("timestamp");
CREATE INDEX IF NOT EXISTS "idx_audit_logs_org_id" ON "public"."audit_logs" USING "btree" ("org_id");

-- Enable RLS on audit logs
ALTER TABLE "public"."audit_logs" ENABLE ROW LEVEL SECURITY;

-- Function to clean up abandoned conversations (24h timeout)
CREATE OR REPLACE FUNCTION "public"."cleanup_abandoned_conversations"()
RETURNS trigger
LANGUAGE "plpgsql" SECURITY DEFINER
SET "search_path" TO ''
AS $
BEGIN
    -- Mark conversations older than 24 hours as resolved_ai
    UPDATE public.conversations 
    SET 
        status = 'resolved_ai',
        resolved_at = CURRENT_TIMESTAMP
    WHERE status = 'ongoing' 
      AND started_at < CURRENT_TIMESTAMP - INTERVAL '24 hours';
    
    RETURN NEW;
END;
$;

-- Function to clean up old messages (7 days for resolved conversations)
CREATE OR REPLACE FUNCTION "public"."cleanup_old_messages"()
RETURNS trigger
LANGUAGE "plpgsql" SECURITY DEFINER
SET "search_path" TO ''
AS $
BEGIN
    -- Delete messages from conversations that have been resolved for more than 7 days
    DELETE FROM public.messages 
    WHERE conv_id IN (
        SELECT c.id 
        FROM public.conversations c 
        WHERE c.status IN ('resolved_ai', 'resolved_human')
          AND c.resolved_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
    );
    
    RETURN NEW;
END;
$;

-- Function to log audit events
CREATE OR REPLACE FUNCTION "public"."log_audit_event"()
RETURNS trigger
LANGUAGE "plpgsql" SECURITY DEFINER
SET "search_path" TO ''
AS $
DECLARE
    audit_user_id uuid;
    audit_org_id uuid;
    audit_ip text;
    audit_user_agent text;
BEGIN
    -- Get user context from current auth
    BEGIN
        audit_user_id := (SELECT auth.uid());
    EXCEPTION WHEN others THEN
        audit_user_id := NULL;
    END;
    
    -- For API key auth, try to get org_id from the record
    IF audit_user_id IS NULL THEN
        IF TG_TABLE_NAME = 'api_keys' THEN
            audit_org_id := NEW.org_id;
        ELSIF TG_TABLE_NAME = 'conversations' THEN
            audit_org_id := (SELECT org_id FROM public.knowledge_bases WHERE id = NEW.kb_id);
        ELSIF TG_TABLE_NAME = 'documents' THEN
            audit_org_id := (SELECT org_id FROM public.knowledge_bases WHERE id = NEW.kb_id);
        END IF;
    END IF;
    
    -- Insert audit log
    INSERT INTO public.audit_logs (
        table_name,
        record_id,
        operation,
        old_values,
        new_values,
        user_id,
        org_id,
        timestamp,
        ip_address,
        user_agent
    ) VALUES (
        TG_TABLE_NAME,
        COALESCE(NEW.id, OLD.id),
        TG_OP,
        CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) ELSE NULL END,
        audit_user_id,
        audit_org_id,
        CURRENT_TIMESTAMP,
        current_setting('request.headers', true)::json->>'x-forwarded-for',
        current_setting('request.headers', true)::json->>'user-agent'
    );
    
    RETURN COALESCE(NEW, OLD);
END;
$;

-- Create conversation status update trigger
CREATE OR REPLACE FUNCTION "public"."update_conversation_metrics"()
RETURNS trigger
LANGUAGE "plpgsql" SECURITY DEFINER
SET "search_path" TO ''
AS $
BEGIN
    -- When conversation status changes, update metrics
    IF TG_OP = 'UPDATE' AND NEW.status != OLD.status THEN
        INSERT INTO public.metrics (
            conv_id,
            resolution_time,
            handoff_triggered,
            created_at
        ) VALUES (
            NEW.id,
            CASE 
                WHEN NEW.status IN ('resolved_ai', 'resolved_human') AND NEW.resolved_at IS NOT NULL 
                THEN EXTRACT(EPOCH FROM (NEW.resolved_at - NEW.started_at))
                ELSE NULL 
            END,
            CASE WHEN NEW.status = 'escalated' THEN true ELSE false END,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (conv_id) DO UPDATE SET
            resolution_time = EXCLUDED.resolution_time,
            handoff_triggered = EXCLUDED.handoff_triggered;
    END IF;
    
    RETURN NEW;
END;
$;

-- Create triggers for audit logging on critical tables
DROP TRIGGER IF EXISTS "audit_api_keys" ON "public"."api_keys";
CREATE TRIGGER "audit_api_keys"
    AFTER INSERT OR UPDATE OR DELETE ON "public"."api_keys"
    FOR EACH ROW EXECUTE FUNCTION "public"."log_audit_event"();

DROP TRIGGER IF EXISTS "audit_conversations" ON "public"."conversations";
CREATE TRIGGER "audit_conversations"
    AFTER INSERT OR UPDATE OR DELETE ON "public"."conversations"
    FOR EACH ROW EXECUTE FUNCTION "public"."log_audit_event"();

DROP TRIGGER IF EXISTS "audit_documents" ON "public"."documents";
CREATE TRIGGER "audit_documents"
    AFTER INSERT OR UPDATE OR DELETE ON "public"."documents"
    FOR EACH ROW EXECUTE FUNCTION "public"."log_audit_event"();

DROP TRIGGER IF EXISTS "audit_users" ON "public"."users";
CREATE TRIGGER "audit_users"
    AFTER INSERT OR UPDATE OR DELETE ON "public"."users"
    FOR EACH ROW EXECUTE FUNCTION "public"."log_audit_event"();

DROP TRIGGER IF EXISTS "audit_organizations" ON "public"."organizations";
CREATE TRIGGER "audit_organizations"
    AFTER INSERT OR UPDATE OR DELETE ON "public"."organizations"
    FOR EACH ROW EXECUTE FUNCTION "public"."log_audit_event"();

-- Create triggers for conversation cleanup and metrics
DROP TRIGGER IF EXISTS "cleanup_abandoned_conversations_trigger" ON "public"."conversations";
CREATE TRIGGER "cleanup_abandoned_conversations_trigger"
    BEFORE INSERT OR UPDATE ON "public"."conversations"
    FOR EACH STATEMENT EXECUTE FUNCTION "public"."cleanup_abandoned_conversations"();

DROP TRIGGER IF EXISTS "cleanup_old_messages_trigger" ON "public"."messages";
CREATE TRIGGER "cleanup_old_messages_trigger"
    BEFORE INSERT OR UPDATE ON "public"."messages"
    FOR EACH STATEMENT EXECUTE FUNCTION "public"."cleanup_old_messages"();

DROP TRIGGER IF EXISTS "update_conversation_metrics_trigger" ON "public"."conversations";
CREATE TRIGGER "update_conversation_metrics_trigger"
    AFTER UPDATE ON "public"."conversations"
    FOR EACH ROW EXECUTE FUNCTION "public"."update_conversation_metrics"();

-- Create function to run maintenance tasks
CREATE OR REPLACE FUNCTION "public"."run_maintenance_tasks"()
RETURNS void
LANGUAGE "plpgsql" SECURITY DEFINER
SET "search_path" TO ''
AS $
BEGIN
    -- Clean up old audit logs (keep for 90 days)
    DELETE FROM public.audit_logs 
    WHERE timestamp < CURRENT_TIMESTAMP - INTERVAL '90 days';
    
    -- Clean up old metrics (keep for 1 year)
    DELETE FROM public.metrics 
    WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 year';
    
    -- Update table statistics for better query planning
    ANALYZE;
    
    -- Log maintenance execution
    INSERT INTO public.audit_logs (
        table_name,
        record_id,
        operation,
        new_values,
        timestamp
    ) VALUES (
        'maintenance',
        gen_random_uuid(),
        'MAINTENANCE',
        jsonb_build_object('task', 'run_maintenance_tasks', 'executed_at', CURRENT_TIMESTAMP),
        CURRENT_TIMESTAMP
    );
END;
$;

-- Grant permissions for new functions and tables
GRANT ALL ON FUNCTION "public"."cleanup_abandoned_conversations"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_abandoned_conversations"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_abandoned_conversations"() TO "service_role";

GRANT ALL ON FUNCTION "public"."cleanup_old_messages"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_old_messages"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_old_messages"() TO "service_role";

GRANT ALL ON FUNCTION "public"."log_audit_event"() TO "anon";
GRANT ALL ON FUNCTION "public"."log_audit_event"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."log_audit_event"() TO "service_role";

GRANT ALL ON FUNCTION "public"."update_conversation_metrics"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_conversation_metrics"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_conversation_metrics"() TO "service_role";

GRANT ALL ON FUNCTION "public"."run_maintenance_tasks"() TO "anon";
GRANT ALL ON FUNCTION "public"."run_maintenance_tasks"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."run_maintenance_tasks"() TO "service_role";

GRANT ALL ON TABLE "public"."audit_logs" TO "anon";
GRANT ALL ON TABLE "public"."audit_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_logs" TO "service_role";

-- =============================================
-- INTEGRATION TABLES FOR WEBHOOK SECURITY
-- =============================================

CREATE TABLE IF NOT EXISTS "public"."integration_configs" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "integration_id" uuid NOT NULL,
    "key" text NOT NULL,
    "value" text NOT NULL,
    "is_secret" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT "now()",
    "updated_at" timestamp with time zone DEFAULT "now()"
);

ALTER TABLE "public"."integration_configs" OWNER TO "postgres";

CREATE TABLE IF NOT EXISTS "public"."integration_events" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "integration_id" uuid NOT NULL,
    "event_type" text NOT NULL,
    "payload" jsonb DEFAULT '{}'::jsonb,
    "status" text DEFAULT 'pending',
    "created_at" timestamp with time zone DEFAULT "now()",
    "processed_at" timestamp with time zone
);

ALTER TABLE "public"."integration_events" OWNER TO "postgres";

CREATE TABLE IF NOT EXISTS "public"."integrations" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "org_id" uuid NOT NULL,
    "type" text NOT NULL,
    "name" text NOT NULL,
    "status" text DEFAULT 'pending',
    "kb_id" uuid NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now()",
    "updated_at" timestamp with time zone DEFAULT "now()"
);

ALTER TABLE "public"."integrations" OWNER TO "postgres";

-- Add indexes for integration tables
CREATE INDEX IF NOT EXISTS "idx_integration_configs_integration_id" ON "public"."integration_configs" USING "btree" ("integration_id");
CREATE INDEX IF NOT EXISTS "idx_integration_configs_key" ON "public"."integration_configs" USING "btree" ("integration_id", "key");
CREATE INDEX IF NOT EXISTS "idx_integration_events_integration_id" ON "public"."integration_events" USING "btree" ("integration_id");
CREATE INDEX IF NOT EXISTS "idx_integration_events_event_type" ON "public"."integration_events" USING "btree" ("event_type");
CREATE INDEX IF NOT EXISTS "idx_integration_events_created_at" ON "public"."integration_events" USING "btree" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_integrations_org_id" ON "public"."integrations" USING "btree" ("org_id");
CREATE INDEX IF NOT EXISTS "idx_integrations_status" ON "public"."integrations" USING "btree" ("status");

-- Add foreign key constraints
ALTER TABLE "public"."integration_configs" 
    ADD CONSTRAINT "integration_configs_integration_id_fkey" 
    FOREIGN KEY ("integration_id") REFERENCES "public"."integrations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."integration_events" 
    ADD CONSTRAINT "integration_events_integration_id_fkey" 
    FOREIGN KEY ("integration_id") REFERENCES "public"."integrations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."integrations" 
    ADD CONSTRAINT "integrations_org_id_fkey" 
    FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."integrations" 
    ADD CONSTRAINT "integrations_kb_id_fkey" 
    FOREIGN KEY ("kb_id") REFERENCES "public"."knowledge_bases"("id") ON DELETE CASCADE;

-- Enable RLS on integration tables
ALTER TABLE "public"."integration_configs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."integration_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."integrations" ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for integration_configs
CREATE POLICY "integration_configs_select" ON "public"."integration_configs" FOR SELECT TO "authenticated"
    USING (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

CREATE POLICY "integration_configs_insert" ON "public"."integration_configs" FOR INSERT TO "authenticated"
    WITH CHECK (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

CREATE POLICY "integration_configs_update" ON "public"."integration_configs" FOR UPDATE TO "authenticated"
    USING (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

CREATE POLICY "integration_configs_delete" ON "public"."integration_configs" FOR DELETE TO "authenticated"
    USING (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

-- Create RLS policies for integration_events
CREATE POLICY "integration_events_select" ON "public"."integration_events" FOR SELECT TO "authenticated"
    USING (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

CREATE POLICY "integration_events_insert" ON "public"."integration_events" FOR INSERT TO "authenticated"
    WITH CHECK (integration_id IN (
        SELECT i.id FROM public.integrations i 
        JOIN public.users u ON u.org_id = i.org_id 
        WHERE u.id = auth.uid()
    ));

-- Create RLS policies for integrations
CREATE POLICY "integrations_select" ON "public"."integrations" FOR SELECT TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "integrations_insert" ON "public"."integrations" FOR INSERT TO "authenticated"
    WITH CHECK (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "integrations_update" ON "public"."integrations" FOR UPDATE TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "integrations_delete" ON "public"."integrations" FOR DELETE TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

-- Grant permissions for new tables
GRANT ALL ON TABLE "public"."integration_configs" TO "anon";
GRANT ALL ON TABLE "public"."integration_configs" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_configs" TO "service_role";

GRANT ALL ON TABLE "public"."integration_events" TO "anon";
GRANT ALL ON TABLE "public"."integration_events" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_events" TO "service_role";

GRANT ALL ON TABLE "public"."integrations" TO "anon";
GRANT ALL ON TABLE "public"."integrations" TO "authenticated";
GRANT ALL ON TABLE "public"."integrations" TO "service_role";

-- =============================================
-- HUMAN AGENT WORKFLOW SYSTEM
-- =============================================

CREATE TABLE IF NOT EXISTS "public"."support_agents" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "user_id" uuid NOT NULL,
    "org_id" uuid NOT NULL,
    "name" text NOT NULL,
    "email" text NOT NULL,
    "role" text DEFAULT 'agent' CHECK (role IN ('agent', 'senior_agent', 'supervisor', 'admin')),
    "status" text DEFAULT 'available' CHECK (status IN ('available', 'busy', 'offline', 'break')),
    "max_concurrent_conversations" integer DEFAULT 3,
    "skills" jsonb DEFAULT '[]'::jsonb,
    "shift_start" time,
    "shift_end" time,
    "timezone" text DEFAULT 'UTC',
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now()",
    "updated_at" timestamp with time zone DEFAULT "now()"
);

CREATE TABLE IF NOT EXISTS "public"."agent_assignments" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "conv_id" uuid NOT NULL,
    "agent_id" uuid NOT NULL,
    "assigned_by" uuid,
    "assignment_type" text DEFAULT 'manual' CHECK (assignment_type IN ('manual', 'automatic', 'escalation')),
    "priority" text DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    "status" text DEFAULT 'active' CHECK (status IN ('active', 'completed', 'transferred', 'escalated')),
    "assigned_at" timestamp with time zone DEFAULT "now()",
    "completed_at" timestamp with time zone,
    "notes" text
);

CREATE TABLE IF NOT EXISTS "public"."agent_queue" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "conv_id" uuid NOT NULL,
    "org_id" uuid NOT NULL,
    "kb_id" uuid,
    "queue_position" integer,
    "priority" text DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    "status" text DEFAULT 'waiting' CHECK (status IN ('waiting', 'assigned', 'cancelled')),
    "reason" text,
    "customer_info" jsonb DEFAULT '{}'::jsonb,
    "enqueued_at" timestamp with time zone DEFAULT "now()",
    "assigned_at" timestamp with time zone,
    "timeout_minutes" integer DEFAULT 30
);

CREATE TABLE IF NOT EXISTS "public"."agent_responses" (
    "id" uuid DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "conv_id" uuid NOT NULL,
    "agent_id" uuid NOT NULL,
    "message_type" text DEFAULT 'text' CHECK (message_type IN ('text', 'file', 'image', 'audio', 'video')),
    "content" text NOT NULL,
    "metadata" jsonb DEFAULT '{}'::jsonb,
    "original_message_id" uuid,
    "sent_at" timestamp with time zone DEFAULT "now()",
    "delivered_at" timestamp with time zone,
    "read_at" timestamp with time zone
);

-- Create indexes for agent system
CREATE INDEX IF NOT EXISTS "idx_support_agents_org_id" ON "public"."support_agents" USING "btree" ("org_id");
CREATE INDEX IF NOT EXISTS "idx_support_agents_user_id" ON "public"."support_agents" USING "btree" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_support_agents_status" ON "public"."support_agents" USING "btree" ("status");
CREATE INDEX IF NOT EXISTS "idx_agent_assignments_conv_id" ON "public"."agent_assignments" USING "btree" ("conv_id");
CREATE INDEX IF NOT EXISTS "idx_agent_assignments_agent_id" ON "public"."agent_assignments" USING "btree" ("agent_id");
CREATE INDEX IF NOT EXISTS "idx_agent_assignments_status" ON "public"."agent_assignments" USING "btree" ("status");
CREATE INDEX IF NOT EXISTS "idx_agent_queue_org_id" ON "public"."agent_queue" USING "btree" ("org_id");
CREATE INDEX IF NOT EXISTS "idx_agent_queue_status" ON "public"."agent_queue" USING "btree" ("status");
CREATE INDEX IF NOT EXISTS "idx_agent_queue_priority" ON "public"."agent_queue" USING "btree" ("priority");
CREATE INDEX IF NOT EXISTS "idx_agent_queue_enqueued_at" ON "public"."agent_queue" USING "btree" ("enqueued_at");
CREATE INDEX IF NOT EXISTS "idx_agent_responses_conv_id" ON "public"."agent_responses" USING "btree" ("conv_id");
CREATE INDEX IF NOT EXISTS "idx_agent_responses_agent_id" ON "public"."agent_responses" USING "btree" ("agent_id");
CREATE INDEX IF NOT EXISTS "idx_agent_responses_sent_at" ON "public"."agent_responses" USING "btree" ("sent_at");

-- Add foreign key constraints
ALTER TABLE "public"."support_agents" 
    ADD CONSTRAINT "support_agents_user_id_fkey" 
    FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE "public"."support_agents" 
    ADD CONSTRAINT "support_agents_org_id_fkey" 
    FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_assignments" 
    ADD CONSTRAINT "agent_assignments_conv_id_fkey" 
    FOREIGN KEY ("conv_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_assignments" 
    ADD CONSTRAINT "agent_assignments_agent_id_fkey" 
    FOREIGN KEY ("agent_id") REFERENCES "public"."support_agents"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_assignments" 
    ADD CONSTRAINT "agent_assignments_assigned_by_fkey" 
    FOREIGN KEY ("assigned_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;

ALTER TABLE "public"."agent_queue" 
    ADD CONSTRAINT "agent_queue_conv_id_fkey" 
    FOREIGN KEY ("conv_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_queue" 
    ADD CONSTRAINT "agent_queue_org_id_fkey" 
    FOREIGN KEY ("org_id") REFERENCES "public"."organizations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_queue" 
    ADD CONSTRAINT "agent_queue_kb_id_fkey" 
    FOREIGN KEY ("kb_id") REFERENCES "public"."knowledge_bases"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_responses" 
    ADD CONSTRAINT "agent_responses_conv_id_fkey" 
    FOREIGN KEY ("conv_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;

ALTER TABLE "public"."agent_responses" 
    ADD CONSTRAINT "agent_responses_agent_id_fkey" 
    FOREIGN KEY ("agent_id") REFERENCES "public"."support_agents"("id") ON DELETE CASCADE;

-- Enable RLS on agent tables
ALTER TABLE "public"."support_agents" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_assignments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_queue" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_responses" ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for support_agents
CREATE POLICY "support_agents_select" ON "public"."support_agents" FOR SELECT TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "support_agents_insert" ON "public"."support_agents" FOR INSERT TO "authenticated"
    WITH CHECK (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "support_agents_update" ON "public"."support_agents" FOR UPDATE TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

-- Create RLS policies for agent_assignments
CREATE POLICY "agent_assignments_select" ON "public"."agent_assignments" FOR SELECT TO "authenticated"
    USING (conv_id IN (
        SELECT c.id FROM public.conversations c
        JOIN public.users u ON u.id = c.user_id
        WHERE u.org_id = (SELECT u2.org_id FROM public.users u2 WHERE u2.id = auth.uid())
    ));

CREATE POLICY "agent_assignments_insert" ON "public"."agent_assignments" FOR INSERT TO "authenticated"
    WITH CHECK (conv_id IN (
        SELECT c.id FROM public.conversations c
        JOIN public.users u ON u.id = c.user_id
        WHERE u.org_id = (SELECT u2.org_id FROM public.users u2 WHERE u2.id = auth.uid())
    ));

CREATE POLICY "agent_assignments_update" ON "public"."agent_assignments" FOR UPDATE TO "authenticated"
    USING (conv_id IN (
        SELECT c.id FROM public.conversations c
        JOIN public.users u ON u.id = c.user_id
        WHERE u.org_id = (SELECT u2.org_id FROM public.users u2 WHERE u2.id = auth.uid())
    ));

-- Create RLS policies for agent_queue
CREATE POLICY "agent_queue_select" ON "public"."agent_queue" FOR SELECT TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "agent_queue_insert" ON "public"."agent_queue" FOR INSERT TO "authenticated"
    WITH CHECK (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

CREATE POLICY "agent_queue_update" ON "public"."agent_queue" FOR UPDATE TO "authenticated"
    USING (org_id IN (
        SELECT u.org_id FROM public.users u WHERE u.id = auth.uid()
    ));

-- Create RLS policies for agent_responses
CREATE POLICY "agent_responses_select" ON "public"."agent_responses" FOR SELECT TO "authenticated"
    USING (conv_id IN (
        SELECT c.id FROM public.conversations c
        JOIN public.users u ON u.id = c.user_id
        WHERE u.org_id = (SELECT u2.org_id FROM public.users u2 WHERE u2.id = auth.uid())
    ));

CREATE POLICY "agent_responses_insert" ON "public"."agent_responses" FOR INSERT TO "authenticated"
    WITH CHECK (conv_id IN (
        SELECT c.id FROM public.conversations c
        JOIN public.users u ON u.id = c.user_id
        WHERE u.org_id = (SELECT u2.org_id FROM public.users u2 WHERE u2.id = auth.uid())
    ));

-- Grant permissions for new tables
GRANT ALL ON TABLE "public"."support_agents" TO "anon";
GRANT ALL ON TABLE "public"."support_agents" TO "authenticated";
GRANT ALL ON TABLE "public"."support_agents" TO "service_role";

GRANT ALL ON TABLE "public"."agent_assignments" TO "anon";
GRANT ALL ON TABLE "public"."agent_assignments" TO "authenticated";
GRANT ALL ON TABLE "public"."agent_assignments" TO "service_role";

GRANT ALL ON TABLE "public"."agent_queue" TO "anon";
GRANT ALL ON TABLE "public"."agent_queue" TO "authenticated";
GRANT ALL ON TABLE "public"."agent_queue" TO "service_role";

GRANT ALL ON TABLE "public"."agent_responses" TO "anon";
GRANT ALL ON TABLE "public"."agent_responses" TO "authenticated";
GRANT ALL ON TABLE "public"."agent_responses" TO "service_role";



