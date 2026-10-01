import Link from "next/link";

export function DraftNotice() {
  return (
    <p role="note" className="mb-6 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
      <strong>Draft template.</strong> This document is a starting-point template, not legal advice. It must be reviewed
      by a qualified lawyer for your jurisdiction before you rely on it or operate this service publicly.
    </p>
  );
}

export function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-8 text-sm leading-relaxed [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc">
      <Link href="/" className="text-blue-600 underline dark:text-blue-400">← Back to app</Link>
      <h1 className="text-2xl font-bold">{title}</h1>
      <DraftNotice />
      {children}
    </main>
  );
}
