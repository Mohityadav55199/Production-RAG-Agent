import { AuthForm } from "@/components/auth/auth-form";

export const metadata = { title: "Log in | RAG Agent" };

export default function LoginPage() {
  return <AuthForm mode="login" />;
}
