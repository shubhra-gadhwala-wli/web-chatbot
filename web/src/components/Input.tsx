import { useId, type InputHTMLAttributes } from "react";
import "./Input.css";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  helperText?: string;
  errorText?: string;
}

export function Input({ label, helperText, errorText, id, className, ...rest }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const helperId = `${inputId}-helper`;
  const errorId = `${inputId}-error`;
  const describedBy = [helperText ? helperId : null, errorText ? errorId : null]
    .filter(Boolean)
    .join(" ") || undefined;

  return (
    <div className={["field", className ?? ""].filter(Boolean).join(" ")}>
      <label htmlFor={inputId} className="field__label">
        {label}
      </label>
      <input
        id={inputId}
        className={["field__input", errorText ? "field__input--error" : ""].filter(Boolean).join(" ")}
        aria-describedby={describedBy}
        aria-invalid={errorText ? true : undefined}
        {...rest}
      />
      {helperText ? (
        <p id={helperId} className="field__helper">
          {helperText}
        </p>
      ) : null}
      {errorText ? (
        <p id={errorId} className="field__error" role="alert">
          {errorText}
        </p>
      ) : null}
    </div>
  );
}
