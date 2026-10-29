import React from "react";
import { Routes, Route } from "react-router-dom";
import CockpitView from "./views/CockpitView";
import AdminDirectorView from "./views/AdminDirectorView";
import PortalAuthGate from "./components/PortalAuthGate";

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <PortalAuthGate portal="cockpit">
            <CockpitView />
          </PortalAuthGate>
        }
      />
      <Route
        path="/admin"
        element={
          <PortalAuthGate portal="admin">
            <AdminDirectorView />
          </PortalAuthGate>
        }
      />
    </Routes>
  );
}
