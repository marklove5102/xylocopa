// Curated emoji set for Project icons.
// Each entry maps a Unicode emoji char → Fluent UI Emoji "Flat" folder name.
// Folder names follow github.com/microsoft/fluentui-emoji/assets/<Folder>/Flat/<snake>_flat.svg

export const DEFAULT_EMOJI_CLOSED = "📁";
export const DEFAULT_EMOJI_OPEN = "📂";

export const FLUENT_MAP = {
  // Folders & Docs
  "📁": "File folder",
  "📂": "Open file folder",
  "🗂️": "Card index dividers",
  "📄": "Page facing up",
  "📋": "Clipboard",
  "📝": "Memo",
  "📎": "Paperclip",
  "🔖": "Bookmark",
  "📊": "Bar chart",
  "📈": "Chart increasing",
  "📉": "Chart decreasing",
  "🗃️": "Card file box",
  "🗄️": "File cabinet",
  "📚": "Books",
  "📖": "Open book",
  "📔": "Notebook with decorative cover",

  // Tech
  "💻": "Laptop",
  "⌨️": "Keyboard",
  "🖥️": "Desktop computer",
  "🖨️": "Printer",
  "💾": "Floppy disk",
  "💿": "Optical disk",
  "📀": "Dvd",
  "🖱️": "Computer mouse",
  "📡": "Satellite antenna",
  "🔌": "Electric plug",
  "🔋": "Battery",
  "⚙️": "Gear",
  "🔧": "Wrench",
  "🛠️": "Hammer and wrench",
  "🔨": "Hammer",
  "🧰": "Toolbox",
  "🐛": "Bug",
  "🔐": "Locked with key",
  "🔑": "Key",
  "🧪": "Test tube",

  // Work & Goals
  "🎯": "Bullseye",
  "🚀": "Rocket",
  "🏁": "Chequered flag",
  "🏆": "Trophy",
  "🎖️": "Military medal",
  "💡": "Light bulb",
  "🧠": "Brain",
  "📌": "Pushpin",
  "📍": "Round pushpin",
  "🗓️": "Spiral calendar",
  "📅": "Calendar",
  "⏰": "Alarm clock",
  "⏳": "Hourglass not done",
  "🔔": "Bell",
  "📢": "Loudspeaker",
  "🗺️": "World map",

  // Creative
  "🎨": "Artist palette",
  "🖼️": "Framed picture",
  "🎬": "Clapper board",
  "🎭": "Performing arts",
  "🎵": "Musical note",
  "🎹": "Musical keyboard",
  "📷": "Camera",
  "🎥": "Movie camera",
  "✏️": "Pencil",
  "🖌️": "Paintbrush",
  "🖍️": "Crayon",
  "🎸": "Guitar",

  // Nature
  "🌱": "Seedling",
  "🌳": "Deciduous tree",
  "🌲": "Evergreen tree",
  "🌊": "Water wave",
  "🔥": "Fire",
  "❄️": "Snowflake",
  "⚡": "High voltage",
  "🌈": "Rainbow",
  "🌞": "Sun with face",
  "🌙": "Crescent moon",
  "⭐": "Star",
  "🍃": "Leaf fluttering in wind",
  "🌸": "Cherry blossom",
  "🌻": "Sunflower",
  "🌷": "Tulip",
  "🪴": "Potted plant",

  // Symbols
  "♻️": "Recycling symbol",
  "✨": "Sparkles",
  "💎": "Gem stone",
  "🎁": "Wrapped gift",
  "🧩": "Puzzle piece",
  "♾️": "Infinity",
  "💬": "Speech balloon",
  "💭": "Thought balloon",
  "🔗": "Link",
  "🛡️": "Shield",
  "🏷️": "Label",
  "📐": "Triangular ruler",
};

export const CATEGORIES = [
  {
    key: "folders",
    label: "Files",
    anchor: "📁",
    emojis: ["📁", "📂", "🗂️", "📄", "📋", "📝", "📎", "🔖", "📊", "📈", "📉", "🗃️", "🗄️", "📚", "📖", "📔"],
  },
  {
    key: "tech",
    label: "Tech",
    anchor: "💻",
    emojis: ["💻", "⌨️", "🖥️", "🖨️", "💾", "💿", "📀", "🖱️", "📡", "🔌", "🔋", "⚙️", "🔧", "🛠️", "🔨", "🧰", "🐛", "🔐", "🔑", "🧪"],
  },
  {
    key: "work",
    label: "Goals",
    anchor: "🎯",
    emojis: ["🎯", "🚀", "🏁", "🏆", "🎖️", "💡", "🧠", "📌", "📍", "🗓️", "📅", "⏰", "⏳", "🔔", "📢", "🗺️"],
  },
  {
    key: "creative",
    label: "Creative",
    anchor: "🎨",
    emojis: ["🎨", "🖼️", "🎬", "🎭", "🎵", "🎹", "📷", "🎥", "✏️", "🖌️", "🖍️", "🎸"],
  },
  {
    key: "nature",
    label: "Nature",
    anchor: "🌱",
    emojis: ["🌱", "🌳", "🌲", "🌊", "🔥", "❄️", "⚡", "🌈", "🌞", "🌙", "⭐", "🍃", "🌸", "🌻", "🌷", "🪴"],
  },
  {
    key: "symbols",
    label: "Symbols",
    anchor: "✨",
    emojis: ["✨", "♻️", "💎", "🎁", "🧩", "♾️", "💬", "💭", "🔗", "🛡️", "🏷️", "📐"],
  },
];

// Lowercase search keywords used by the picker's search box.
export const KEYWORDS = {
  "📁": "folder directory file closed",
  "📂": "folder open directory active",
  "🗂️": "dividers index files organize",
  "📄": "page doc document",
  "📋": "clipboard tasks list",
  "📝": "memo note write",
  "📎": "paperclip attach",
  "🔖": "bookmark save",
  "📊": "bar chart stats",
  "📈": "chart up growth trending",
  "📉": "chart down decline",
  "🗃️": "card file box archive",
  "🗄️": "cabinet archive",
  "📚": "books library",
  "📖": "book read open",
  "📔": "notebook journal",
  "💻": "laptop computer mac",
  "⌨️": "keyboard",
  "🖥️": "desktop computer",
  "🖨️": "printer print",
  "💾": "floppy save disk",
  "💿": "cd optical disk",
  "📀": "dvd disc",
  "🖱️": "mouse",
  "📡": "satellite antenna signal",
  "🔌": "plug power",
  "🔋": "battery",
  "⚙️": "gear settings config",
  "🔧": "wrench tool fix",
  "🛠️": "tools build",
  "🔨": "hammer build",
  "🧰": "toolbox",
  "🐛": "bug debug",
  "🔐": "lock secure security auth",
  "🔑": "key secret",
  "🧪": "test lab experiment",
  "🎯": "target goal bullseye",
  "🚀": "rocket launch ship fast",
  "🏁": "flag finish done race",
  "🏆": "trophy win",
  "🎖️": "medal award",
  "💡": "idea light bulb",
  "🧠": "brain mind thinking",
  "📌": "pin location",
  "📍": "pin location map",
  "🗓️": "calendar date",
  "📅": "calendar date day",
  "⏰": "alarm clock time",
  "⏳": "hourglass time wait",
  "🔔": "bell notify alert",
  "📢": "announce loudspeaker",
  "🗺️": "map world",
  "🎨": "art design palette",
  "🖼️": "picture frame image",
  "🎬": "movie film clapper",
  "🎭": "theatre performance",
  "🎵": "music note",
  "🎹": "piano keyboard music",
  "📷": "camera photo",
  "🎥": "video movie camera",
  "✏️": "pencil write edit",
  "🖌️": "paintbrush paint",
  "🖍️": "crayon",
  "🎸": "guitar music",
  "🌱": "plant seedling grow new",
  "🌳": "tree nature",
  "🌲": "evergreen tree pine",
  "🌊": "wave water ocean",
  "🔥": "fire hot trending",
  "❄️": "snow cold winter",
  "⚡": "lightning electric fast",
  "🌈": "rainbow pride",
  "🌞": "sun bright",
  "🌙": "moon night",
  "⭐": "star favorite",
  "🍃": "leaf wind",
  "🌸": "cherry blossom flower",
  "🌻": "sunflower",
  "🌷": "tulip flower",
  "🪴": "potted plant",
  "♻️": "recycle green eco",
  "✨": "sparkles magic shine",
  "💎": "gem diamond premium",
  "🎁": "gift present",
  "🧩": "puzzle piece",
  "♾️": "infinity endless",
  "💬": "speech chat comment",
  "💭": "thought bubble",
  "🔗": "link url chain",
  "🛡️": "shield protect",
  "🏷️": "label tag",
  "📐": "ruler measure",
};

/**
 * Return the Fluent UI Emoji Flat SVG URL for a given emoji character,
 * or null if the emoji is not in our curated set.
 */
export function fluentFlatUrl(char) {
  const folder = FLUENT_MAP[char];
  if (!folder) return null;
  const file = folder.toLowerCase().replace(/[\s-]+/g, "_");
  return `https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets/${encodeURIComponent(folder)}/Flat/${file}_flat.svg`;
}

/**
 * Decide which default emoji to show for a project that has no custom emoji.
 */
export function defaultProjectEmoji({ hasActiveAgents }) {
  return hasActiveAgents ? DEFAULT_EMOJI_OPEN : DEFAULT_EMOJI_CLOSED;
}

/** Flat list of all curated emojis (for search). */
export const ALL_EMOJIS = CATEGORIES.flatMap(c => c.emojis);
