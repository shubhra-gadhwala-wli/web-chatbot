import { useCallback, useEffect, useRef, useState } from "react";

// Chrome-only Web Speech API; no polyfill or streaming vendor per architecture.
type SpeechRecognitionCtor = new () => SpeechRecognition;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isSpeechRecognitionSupported(): boolean {
  return getRecognitionCtor() !== null;
}

interface UseSpeechRecognitionResult {
  listening: boolean;
  errorMessage: string | null;
  start: () => void;
  stop: () => void;
}

export function useSpeechRecognition(onTranscript: (text: string, isFinal: boolean) => void): UseSpeechRecognitionResult {
  const [listening, setListening] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      recognitionRef.current?.stop();
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    },
    [],
  );

  const showTransientError = useCallback((message: string) => {
    setErrorMessage(message);
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    errorTimerRef.current = setTimeout(() => setErrorMessage(null), 4000);
  }, []);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    const recognition = new Ctor();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      const result = event.results[event.results.length - 1];
      onTranscript(result[0].transcript, result.isFinal);
    };
    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        showTransientError("Didn't catch that — check your microphone permission");
      } else if (event.error === "no-speech") {
        showTransientError("No speech detected — try again");
      } else {
        showTransientError("No speech detected — try again");
      }
      setListening(false);
    };
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [onTranscript, showTransientError]);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
  }, []);

  return { listening, errorMessage, start, stop };
}
