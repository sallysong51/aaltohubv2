/**
 * Home page - redirects are handled by HomeRedirect in App.tsx
 * This component is kept as a minimal fallback.
 */
import { useLocation } from 'wouter';
import { useEffect } from 'react';

export default function Home() {
  const [, setLocation] = useLocation();

  useEffect(() => {
    setLocation('/');
  }, [setLocation]);

  return null;
}
