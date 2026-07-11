"use client";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { SpatialWindow } from "@/spatial/SpatialWindow";

export default function SpatialPage() {
  return (
    <ErrorBoundary label="3D view unavailable">
      <SpatialWindow />
    </ErrorBoundary>
  );
}
