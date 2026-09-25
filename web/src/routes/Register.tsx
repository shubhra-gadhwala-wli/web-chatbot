import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { useAuth } from "../hooks/useAuth";
import "./AuthCard.css";

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setEmailError(null);
    setPasswordError(null);
    setSubmitting(true);
    try {
      await register(email, password);
      navigate("/documents", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "state_conflict") {
        setEmailError("That email is already registered — log in instead");
      } else if (err instanceof ApiError && err.code === "validation_error") {
        setPasswordError(err.message);
      } else {
        setPasswordError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-card__title">Create your account</h1>
        <form onSubmit={onSubmit} noValidate>
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
          />
          {emailError ? (
            <p className="auth-card__banner" role="alert">
              That email is already registered —{" "}
              <Link to="/login">log in instead</Link>
            </p>
          ) : null}
          <Input
            label="Password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
            helperText="At least 12 characters"
            errorText={passwordError ?? undefined}
          />
          <button
            type="button"
            className="auth-card__toggle"
            onClick={() => setShowPassword((v) => !v)}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, marginTop: -12, marginBottom: 16, color: "var(--color-text-secondary)" }}
          >
            {showPassword ? "Hide password" : "Show password"}
          </button>
          <Button type="submit" fullWidth loading={submitting}>
            Create account
          </Button>
        </form>
        <p className="auth-card__footer">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
