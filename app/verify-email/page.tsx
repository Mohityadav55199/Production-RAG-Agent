import { Suspense } from "react";
import { VerifyEmail } from "@/components/auth/verify-email";

export const metadata = { title: "Confirm your email | RAG Agent" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}
