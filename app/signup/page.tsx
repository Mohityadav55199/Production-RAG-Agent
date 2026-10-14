import { AuthForm } from "@/components/auth/auth-form";

export const metadata = { title: "Sign up | RAG Agent" };

export default function SignupPage() {
  return <AuthForm mode="signup" />;
}
