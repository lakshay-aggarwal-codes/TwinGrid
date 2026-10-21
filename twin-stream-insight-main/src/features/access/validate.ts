/** Pure inline validation for the request form. Messages are user-facing; the server stays the authority. */
export interface RequestFields {
  name: string;
  email: string;
  purpose: string;
}
export type RequestErrors = Partial<Record<keyof RequestFields, string>>;

export const NAME_MAX = 100;
export const PURPOSE_MAX = 500;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateRequest(f: RequestFields): RequestErrors {
  const errors: RequestErrors = {};
  const name = f.name.trim();
  const email = f.email.trim();
  if (!name) errors.name = 'Enter your name.';
  else if (name.length > NAME_MAX) errors.name = `Use at most ${NAME_MAX} characters for your name.`;
  if (!email) errors.email = 'Enter your email address.';
  else if (!EMAIL_RE.test(email)) errors.email = 'Enter an email address like name@example.com.';
  if (f.purpose.trim().length > PURPOSE_MAX) errors.purpose = `Use at most ${PURPOSE_MAX} characters.`;
  return errors;
}
