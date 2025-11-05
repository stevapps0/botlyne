

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
    "resolved_at" timestamp with time zone
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
    "team_size" integer
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



