'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Loader2, CheckCircle, AlertCircle, Sparkles } from 'lucide-react';
import { api } from '@/lib/api';

type AuthStatus = 'idle' | 'generating' | 'waiting' | 'verified' | 'error';

export default function LoginPage() {
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus>('idle');
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Generate a random 4-digit code
  const generateCode = () => {
    return String(Math.floor(1000 + Math.random() * 9000));
  };

  // Get client IP (simplified - use actual IP in production)
  const getClientIP = () => '127.0.0.1';

  // Start auth flow
  const handleGenerateCode = async () => {
    setStatus('generating');
    setError(null);

    const newCode = generateCode();

    try {
      await api.post('/auth/init', {
        code: newCode,
        ip: getClientIP(),
      });

      setCode(newCode);
      setStatus('waiting');
      startPolling(newCode);
    } catch (err: unknown) {
      console.error('Failed to initialize auth:', err);
      setError('Failed to generate code. Please try again.');
      setStatus('error');
    }
  };

  // Poll for verification
  const startPolling = useCallback((authCode: string) => {
    // Clear any existing polling
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    pollingRef.current = setInterval(async () => {
      try {
        const response = await api.post('/auth/verify', { code: authCode });
        const data = response.data;

        if (data.status === 'verified' && data.token) {
          // Success! Save token and redirect
          localStorage.setItem('plasma_token', data.token);
          setStatus('verified');

          // Stop polling
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }

          // Redirect after brief celebration
          setTimeout(() => {
            router.push('/dashboard');
          }, 1500);
        }
      } catch (err: unknown) {
        // Check if session expired (410 Gone)
        if (err && typeof err === 'object' && 'response' in err) {
          const axiosError = err as { response?: { status?: number } };
          if (axiosError.response?.status === 410) {
            setError('Code expired. Please generate a new one.');
            setStatus('error');
            if (pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }
          }
        }
      }
    }, 2000);
  }, [router]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  return (
    <div className="gradient-bg min-h-screen flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="glass-card rounded-3xl p-8 md:p-12 max-w-md w-full text-center"
      >
        {/* Logo / Brand */}
        <motion.div
          initial={{ scale: 0.8 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.2, type: 'spring', stiffness: 200 }}
          className="mb-8"
        >
          <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <Sparkles className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
            Plasma AI
          </h1>
          <p className="text-gray-500 mt-2">Procurement Intelligence Platform</p>
        </motion.div>

        {/* Status-based content */}
        <AnimatePresence mode="wait">
          {status === 'idle' && (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <p className="text-gray-400 mb-8">
                Connect your Telegram account to access the platform.
              </p>
              <button
                onClick={handleGenerateCode}
                className="btn-primary w-full py-4 px-6 rounded-xl text-white font-semibold flex items-center justify-center gap-3"
              >
                <Send className="w-5 h-5" />
                Generate Login Code
              </button>
            </motion.div>
          )}

          {status === 'generating' && (
            <motion.div
              key="generating"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="py-8"
            >
              <Loader2 className="w-12 h-12 mx-auto text-indigo-500 animate-spin" />
              <p className="text-gray-400 mt-4">Generating code...</p>
            </motion.div>
          )}

          {status === 'waiting' && code && (
            <motion.div
              key="waiting"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
            >
              <p className="text-gray-400 mb-6">
                Send this code to our Telegram bot:
              </p>
              <div className="code-display py-6 mb-6">{code}</div>
              <a
                href="https://t.me/plasmaosbot"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 bg-[#0088cc] hover:bg-[#0077b5] text-white py-3 px-6 rounded-xl font-semibold transition-all"
              >
                <Send className="w-5 h-5" />
                Open Telegram Bot
              </a>
              <div className="mt-8 flex items-center justify-center gap-2 text-gray-500 pulse-glow">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Waiting for verification...</span>
              </div>
            </motion.div>
          )}

          {status === 'verified' && (
            <motion.div
              key="verified"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              className="py-8"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 300 }}
              >
                <CheckCircle className="w-16 h-16 mx-auto text-green-500" />
              </motion.div>
              <p className="text-green-400 mt-4 font-semibold">
                Login Verified!
              </p>
              <p className="text-gray-500 mt-2">Redirecting to dashboard...</p>
            </motion.div>
          )}

          {status === 'error' && (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <AlertCircle className="w-12 h-12 mx-auto text-red-500 mb-4" />
              <p className="text-red-400 mb-6">{error}</p>
              <button
                onClick={handleGenerateCode}
                className="btn-primary w-full py-4 px-6 rounded-xl text-white font-semibold"
              >
                Try Again
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
