"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { MessageSquare, Settings2, ArrowRight } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { quickActions } from "@/lib/types";

const iconMap = {
  message: MessageSquare,
  settings: Settings2,
};

export function QuickActions() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
    >
      <Card>
        <CardHeader>
          <CardTitle>What next?</CardTitle>
          <CardDescription>
            Once a document shows &quot;Completed&quot;, you can use it here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {quickActions.map((action) => {
            const Icon = iconMap[action.icon];
            return (
              <Link
                key={action.id}
                href={action.href}
                className="group flex items-start gap-3 rounded-xl border p-4 transition-colors hover:border-primary/30 hover:bg-primary/5"
              >
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{action.label}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {action.description}
                  </p>
                </div>
                <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Link>
            );
          })}
        </CardContent>
      </Card>
    </motion.div>
  );
}
