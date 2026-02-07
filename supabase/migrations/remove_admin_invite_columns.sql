-- Migration: Remove admin invite functionality
-- This removes the admin_invited and admin_invite_error columns from groups table
-- Run this in your Supabase SQL Editor

-- Remove admin_invited and admin_invite_error columns
ALTER TABLE groups DROP COLUMN IF EXISTS admin_invited;
ALTER TABLE groups DROP COLUMN IF EXISTS admin_invite_error;

-- Note: The groups table uses groups in Supabase
-- If you're using a different setup, you may need to adjust the table name
