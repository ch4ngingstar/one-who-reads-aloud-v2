/**
 * Recommended Shadow-Slave sound-design vocabulary. Mirrors CUE_VOCAB in
 * src/cue_io.py — the FIXED set of tags Claude is prompted against. The library
 * UI shows these as "recommended" slots so you know what to source/upload, and
 * the cue editor offers them in tag dropdowns.
 */
import type { SfxCategory } from './types'

export const SFX_CATALOG: Record<SfxCategory, string[]> = {
  ambience: [
    'dream_realm_void', 'nightmare_whispers', 'antarctic_wind', 'cold_rain',
    'dungeon_drip', 'ruined_halls', 'forest_night', 'market_crowd',
    'tavern_murmur', 'open_sea', 'storm_surge', 'campfire_night',
    'sanctuary_calm',
  ],
  sfx: [
    'sword_clash', 'sword_draw', 'shield_block', 'arrow_whoosh', 'bone_crack',
    'monster_roar', 'monster_screech', 'flesh_tear', 'magic_cast',
    'shadow_whoosh', 'rune_activate', 'spell_notification', 'heartbeat',
    'door_creak', 'chains_rattle', 'footsteps_stone', 'thunder_crack',
    'fire_burst', 'water_splash', 'crowd_gasp',
  ],
  music: [
    'dread_low_drone', 'sorrow_strings', 'tension_rise', 'battle_pulse',
    'triumph_swell', 'eerie_choir', 'mystery_shimmer',
  ],
}

export const SFX_CATEGORIES: SfxCategory[] = ['ambience', 'sfx', 'music']

export const CATEGORY_LABEL: Record<SfxCategory, string> = {
  ambience: 'Ambience beds',
  sfx: 'Sound effects',
  music: 'Music',
}

/** Pretty display name from a snake_case tag: 'cold_rain' -> 'Cold Rain'. */
export function tagLabel(tag: string): string {
  return tag.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
