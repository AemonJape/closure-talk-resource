import glob
from pathlib import Path
from typing import Dict, List, Tuple

from omegaconf import OmegaConf

from blue_archive.common import (CharData, CharLangData, GroupData,
                                 GroupLangData, all_langs, name_to_id)
from utils.json_utils import read_json
from utils.models import Character, FilterGroup
from utils.resource_utils import ResourceProcessor

script_dir = Path(__file__).parent


def get_legacy_image_mappings() -> dict[str, str]:
    mappings: dict[str, str] = read_json(script_dir / "legacy/img_mappings.json")
    return {
        v.split("/")[-1]: k for k, v in mappings.items() if len(v) > 0
    }


def get_default_lang_data(data: CharData) -> CharLangData:
    if len(data.family_name) > 0:
        jp_name = f"{data.family_name} {data.personal_name}"
        if len(data.personal_name_ruby) > 0:
            en_name = f"{name_to_id(data.family_name_ruby)} {name_to_id(data.personal_name_ruby)}"
        else:
            en_name = f"{name_to_id(data.family_name_ruby)} {data.id}"
        kr_name = f"{data.family_name_kr} {data.personal_name_kr}".strip()
    else:
        jp_name = data.personal_name
        en_name = " ".join([s[0].upper() + s[1:] for s in data.id.split("_") if s != "npc"])
        kr_name = ""

    return OmegaConf.structured(CharLangData(
        data.id,
        {
            "ja": jp_name,
            "en": en_name,
            "ko": kr_name,
            "zh-cn": "",
            "zh-tw": "",
        },
    ))


class BlueArchiveResourceProcessor(ResourceProcessor):
    def __init__(self) -> None:
        super().__init__("ba")

    def get_chars(self) -> Tuple[List[Character], Dict[str, Path]]:
        res_root = self.res_root / "assets"

        char_data = read_json(script_dir / "data/char_data.json")
        char_data: list[CharData] = [CharData.from_dict(d) for d in char_data]

        club_data: list[GroupData] = OmegaConf.load(script_dir / "manual/clubs.yaml")
        school_data: list[GroupData] = OmegaConf.load(script_dir / "manual/schools.yaml")
        group_data = club_data + school_data

        with open(script_dir / "lang/char.yaml", "r", encoding="utf-8") as f:
            translations = OmegaConf.load(f)
            translations: dict[str, CharLangData] = {t.id: t for t in translations}

        with open(script_dir / "manual/excluded_portraits.txt", "r", encoding="utf-8") as f:
            excluded_portraits = set([l.strip() for l in f.readlines()])

        result = []
        avatar_files = {}
        image_config = {}
        image_mappings = get_legacy_image_mappings()
        updated_translations = False
        chars_without_school: list[Character] = []
        chars_without_club: list[Character] = []

        for data in char_data:
            cid = data.id
            default_trans = get_default_lang_data(data)

            if cid not in translations:
                print(f"New translation: {cid}")
                trans = default_trans
                translations[cid] = default_trans
                updated_translations = True
            else:
                trans = translations[cid]
                default_ja_name = default_trans.name["ja"]
                # Japanese name updates when family names are known
                if trans.name["ja"] != default_ja_name and trans.name["ja"] != "初音ミク":
                    print(f"Update name: {default_ja_name}")
                    for lang in ["ja", "en"]:
                        trans.name[lang] = default_trans.name[lang]
                    updated_translations = True
                for lang in all_langs:
                    trans_name = OmegaConf.to_container(trans.name)
                    if lang not in trans_name:
                        trans_name[lang] = default_trans.name[lang]
                        trans.name = OmegaConf.create(trans_name)
                        updated_translations = True

            short_name = dict(trans.short_name) if "short_name" in trans and trans.short_name is not None else {}
            for lang in all_langs:
                if lang not in short_name or len(short_name[lang]) == 0:
                    short_name[lang] = trans.name[lang].split(" ")[-1]

            char = Character(
                cid,
                translations[cid].name,
                short_name,
                [],
                sorted([gp.id for gp in group_data if cid in gp.members]),
            )

            # Get avatar files
            for img in data.image_files:
                name = img.split("/")[-1]
                if name in excluded_portraits:
                    continue

                if name in image_mappings:
                    name = image_mappings[name]
                else:
                    name = name[name.index("Portrait_")+len("Portrait_"):]
                assert len(name) > 0
                assert name not in avatar_files, f"Duplicate: {name}"

                img_file = res_root / f"{img}.png"
                assert img_file.exists(), str(img_file)

                char.images.append(name)
                avatar_files[name] = img_file
                if img_file.stem.endswith("_Collection"):
                    image_config[str(img_file)] = {
                        "h_crop": "top"
                    }

            char.images = sorted(char.images)
            result.append(char)
            if len([gp for gp in school_data if cid in gp.members]) == 0:
                chars_without_school.append(char)
            if len([gp for gp in club_data if cid in gp.members]) == 0:
                chars_without_club.append(char)

        if updated_translations:
            with open(script_dir / "lang/char.yaml", "w", encoding="utf-8") as f:
                f.write(OmegaConf.to_yaml(
                    sorted(translations.values(), key=lambda x: x.id.lower()), sort_keys=True))

        with open(script_dir / "manual/noschool.generated.txt", "w", encoding="utf-8") as f:
            for char in chars_without_school:
                f.write(f"{char.id}\n  {char.names['ja']}\n  {char.images[0]}\n\n")
        with open(script_dir / "manual/noclub.generated.txt", "w", encoding="utf-8") as f:
            for char in chars_without_club:
                f.write(f"{char.id}\n  {char.names['ja']}\n  {char.images[0]}\n\n")

        return result, avatar_files, image_config

    def get_stamps(self) -> List[str]:
        in_root = self.res_root / "assets/UIs/01_Common/31_ClanEmoji"
        files = list(glob.glob(str(in_root / "*_Jp.png")))
        # ClanChat_Emoji_100_Jp
        return sorted(files, key=lambda s: int(s.split("/")[-1].split("_")[2]))

    def get_filters(self) -> List[FilterGroup]:
        result = []
        type_names = OmegaConf.to_container(OmegaConf.load(script_dir / "lang/group_types.yaml"))
        for key in ["schools", "clubs"]:
            groups: list[GroupLangData] = OmegaConf.load(script_dir / f"lang/{key}.yaml")
            groups = sorted(groups, key=lambda gp: gp.id)
            for gp in groups:
                gp.name = OmegaConf.to_container(gp.name)
                gp.name = {k: gp.name[k] or "" for k in all_langs}
            result.append(FilterGroup(
                key,
                type_names[key],
                [gp.id for gp in groups],
                [gp.name for gp in groups],
                [False] * len(groups),
            ))

        return result


if __name__ == "__main__":
    BlueArchiveResourceProcessor().main()
