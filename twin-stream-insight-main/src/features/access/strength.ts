/**
 * A password strength HINT for the activation form. It never blocks anything by itself and is not a security
 * check: the server enforces the real rules (12-128 characters). Pure, exported for tests.
 */
export interface Strength {
  level: 0 | 1 | 2 | 3;
  label: 'Too short' | 'Fair' | 'Good' | 'Strong';
  hint: string;
}

export function passwordStrength(password: string, min = 12): Strength {
  if (password.length < min) {
    return { level: 0, label: 'Too short', hint: `Use at least ${min} characters (${password.length} so far).` };
  }
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  const score = classes + (password.length >= 16 ? 1 : 0);
  if (score >= 4) return { level: 3, label: 'Strong', hint: 'Long and varied. Good.' };
  if (score === 3) return { level: 2, label: 'Good', hint: 'Adding a longer phrase or another kind of character makes it stronger.' };
  return { level: 1, label: 'Fair', hint: 'Mix upper and lower case, numbers or symbols, or make it longer.' };
}
