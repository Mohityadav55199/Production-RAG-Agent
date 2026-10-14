"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuth } from "@/lib/context/auth-context";

export function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const initials = user.email.slice(0, 2).toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex size-9 items-center justify-center rounded-full bg-gradient-to-br from-primary to-violet-600 text-xs font-semibold text-white shadow-sm outline-none ring-offset-background transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {initials}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-11 z-50 w-64 overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg"
        >
          <div className="border-b px-4 py-3">
            <p className="text-xs text-muted-foreground">Signed in as</p>
            <p className="truncate text-sm font-medium">{user.email}</p>
            {user.is_admin && (
              <span className="mt-1 inline-block rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                Administrator
              </span>
            )}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              logout();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted"
          >
            <LogOut className="size-4" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
