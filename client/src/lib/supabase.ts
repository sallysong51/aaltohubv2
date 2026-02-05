/**
 * Supabase client for realtime message subscriptions
 */
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://ejbozuggauzivpznzngu.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

if (!supabaseAnonKey) {
  console.warn('VITE_SUPABASE_ANON_KEY is not set. Realtime features will not work.');
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export default supabase;
