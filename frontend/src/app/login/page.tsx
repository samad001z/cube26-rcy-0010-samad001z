import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { expired } = await searchParams;
  return (
    <div className="mx-auto mt-10 max-w-md">
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-muted">
        Use your organisation&apos;s API key. It is kept in a server-side cookie for 8 hours and
        is never readable by scripts on this page.
      </p>
      {expired && (
        <p className="mt-3 text-sm text-review">Your key was not accepted any more. Sign in again.</p>
      )}
      <LoginForm />
    </div>
  );
}
