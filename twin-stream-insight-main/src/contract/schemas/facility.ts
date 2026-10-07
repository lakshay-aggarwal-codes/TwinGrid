/** BC-08: GET /api/facility, /api/assets, /api/assets/{id}/edges (Pydantic-typed on the backend). */
import { z } from 'zod';
import { num } from './common';

export const Facility = z
  .object({
    id: num,
    name: z.string(),
    frame_unit: z.string(),
    frame_note: z.string(),
    created_at: z.string(),
  })
  .passthrough();
export type Facility = z.output<typeof Facility>;

export const Pose = z
  .object({
    x: num,
    y: num,
    z: num,
    rotation_deg: num,
    valid_from: z.string(),
    valid_to: z.string().nullable(),
  })
  .passthrough();
export type Pose = z.output<typeof Pose>;

export const LocatedIn = z
  .object({
    edge_id: num,
    parent_asset_id: num,
    parent_external_id: z.string().nullable(),
    valid_from: z.string(),
    valid_to: z.string().nullable(),
  })
  .passthrough();
export type LocatedIn = z.output<typeof LocatedIn>;

export const Asset = z
  .object({
    id: num,
    external_id: z.string(),
    name: z.string(),
    asset_type: z.string(),
    retired_at: z.string().nullable(),
    pose: Pose.nullable(),
    located_in: LocatedIn.nullable(),
  })
  .passthrough();
export type Asset = z.output<typeof Asset>;

export const AssetsResponse = z
  .object({
    facility_id: num,
    frame_unit: z.string(),
    as_of: z.string(),
    count: num,
    assets: z.array(Asset),
  })
  .passthrough();
export type AssetsResponse = z.output<typeof AssetsResponse>;

const AssetRef = z.object({ id: num, external_id: z.string(), asset_type: z.string() }).passthrough();

export const Edge = z
  .object({
    id: num,
    relation: z.string(),
    parent: AssetRef,
    child: AssetRef,
    valid_from: z.string(),
    valid_to: z.string().nullable(),
  })
  .passthrough();
export type Edge = z.output<typeof Edge>;

export const EdgesResponse = z
  .object({
    asset_id: num,
    as_of: z.string(),
    include_history: z.boolean(),
    edges: z.array(Edge),
  })
  .passthrough();
export type EdgesResponse = z.output<typeof EdgesResponse>;
