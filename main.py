# invite: https://discord.com/api/oauth2/authorize?client_id=1014899163361722399&permissions=277025409024&scope=bot%20applications.commands

import typing
from datetime import datetime, timezone
import os

import requests

import discord
from discord import app_commands


class CodeRunnerClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)


client = CodeRunnerClient()
# DEPLOY TODO: change SYNC_GUILD to None for global sync
SYNC_GUILD = discord.Object(id=851838718318215208)


# todo: add log messages
def console_log_with_time(msg: str, **kwargs):
    print(f'[code] {datetime.now(tz=timezone.utc):%Y/%m/%d %H:%M:%S%z} - {msg}', **kwargs)


def get_api_list() -> list:
    return requests.get('https://wandbox.org/api/list.json').json()


def get_languages() -> dict:
    langs = dict()
    for item in get_api_list():
        new_item = {'name': item['name'], 'version': item['version']}
        if item['language'] in langs:
            langs[item['language']].append(new_item)
        else:
            langs[item['language']] = [new_item]
    return langs


def run_code(raw_code: str, compiler: str) -> tuple:
    # todo: compiler options?
    post_json = {
        'code': raw_code,
        'options': '',
        'compiler': compiler,
        'compiler-option-raw': ''
    }
    post = requests.post(
        'https://wandbox.org/api/compile.json',
        json=post_json, headers={'Content-type': 'application/json'}
    )
    return post.status_code, post.json()


# todo: generalise and make for version select too
class LanguageSelectMenuView(discord.ui.View):
    def __init__(self, inter: discord.Interaction):
        super().__init__()
        self.origin_inter = inter

        self.language_dict = get_languages()

        self.pages_req = len(self.language_dict) // 25 + 1  # Discord limits Select menus to 25 items
        self.current_page = 0

        langs = sorted(self.language_dict.keys())
        self.lang_selects = []
        for p in range(self.pages_req):
            self.lang_selects.append(LanguageSelect(
                inter, langs[p*25:(p+1)*25], self.language_dict, p
            ))

        self.btn_back = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label='⬅️ Back',
            row=1,
            disabled=True
        )
        self.btn_back.callback = self.btn_back_callback

        self.btn_next = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label='Next ➡️',
            row=1,
            disabled=True
        )
        self.btn_next.callback = self.btn_next_callback

        if self.pages_req > 1:  # buttons required if more than one 'page'
            self.add_item(self.btn_back)
            self.add_item(self.btn_next)

            self.btn_next.disabled = False

        self.add_item(self.lang_selects[self.current_page])

    async def btn_back_callback(self, inter: discord.Interaction):
        await self.change_page(inter, -1)

    async def btn_next_callback(self, inter: discord.Interaction):
        await self.change_page(inter, 1)

    async def change_page(self, inter: discord.Interaction, change: int):
        self.remove_item(self.lang_selects[self.current_page])
        self.current_page += change
        self.add_item(self.lang_selects[self.current_page])

        if self.current_page == 0:
            self.btn_back.disabled = True
        else:
            self.btn_back.disabled = False

        if self.current_page == self.pages_req - 1:
            self.btn_next.disabled = True
        else:
            self.btn_next.disabled = False

        original_resp = await self.origin_inter.original_response()
        await self.origin_inter.edit_original_response(
            content=original_resp.content,
            view=self,
        )
        await inter.response.defer()


class LanguageSelect(discord.ui.Select):
    def __init__(self, inter: discord.Interaction, sorted_options: list, language_dict: dict, p: int):
        self.origin_inter_to_edit = inter
        self.language_dict = language_dict

        super().__init__(
            placeholder=f'[{p+1}] Select a programming language',
            min_values=1, max_values=1, row=0
        )

        if len(sorted_options) > 25:
            raise ValueError('A Select Object may only have 25 options')

        for lang in sorted_options:
            self.add_option(label=lang)

    async def callback(self, inter: discord.Interaction):
        selected_lang = self.values[0]
        version_select_view = discord.ui.View()
        version_select_view.add_item(VersionSelect(
            self.origin_inter_to_edit, self.language_dict, selected_lang
        ))
        await self.origin_inter_to_edit.edit_original_response(
            content='Select the language version.',
            view=version_select_view
        )
        await inter.response.defer()


class VersionSelect(discord.ui.Select):
    def __init__(self, inter: discord.Interaction, language_dict: dict, selected_language: str):
        self.origin_inter_to_edit = inter
        self.selected_language = selected_language

        super().__init__(placeholder='Select a language version', min_values=1, max_values=1)

        for o in language_dict[self.selected_language]:
            self.add_option(label=o['name'], description=o['version'])

    async def callback(self, inter: discord.Interaction):
        selected_version = self.values[0]
        await inter.response.send_modal(
            CodeEntry(self.selected_language, selected_version, self.origin_inter_to_edit)
        )


class RunResponse(typing.TypedDict):
    status: str
    compiler_output: str
    compiler_error: str
    program_output: str
    program_error: str
    program_message: str


class CodeEntry(discord.ui.Modal, title='Enter your Code'):
    code_entry = discord.ui.TextInput(label='Code', style=discord.TextStyle.paragraph)

    def __init__(self, language: str, version: str, origin_inter_to_edit: discord.Interaction):
        super().__init__()
        self.language = language
        self.version = version
        self.origin_inter_to_edit = origin_inter_to_edit

    async def on_submit(self, inter: discord.Interaction):
        highlight_lang = self.language.split(" ")[0].lower()

        await self.origin_inter_to_edit.edit_original_response(
            content=f'{self.language} | {self.version}\n'
                    f'Code:\n```{highlight_lang}\n{self.code_entry}```',
            view=None
        )

        await inter.response.defer(thinking=True)

        error = ''
        result: RunResponse = dict()
        try:
            status, result = run_code(str(self.code_entry), self.version)
        except Exception as e:
            error = str(e)
        else:
            if status != 200:
                error = f'The POST request received a status of {status}.'

        if error:
            await inter.followup.send(
                content='The *request* to run your code failed (i.e. **not** the code itself).\n'
                        f'The following exception was raised by the program:\n```{error}```')
        else:
            if 'status' not in result and 'signal' in result:
                result['status'] = result['signal']

            if int(result['status']) == 0:
                result_colour = discord.Colour.green()
            elif int(result['status']) == 1:
                result_colour = discord.Colour.red()
            else:
                result_colour = discord.Colour.blurple()

            result_embed = discord.Embed(
                title='💻 Code Runner Result',
                colour=result_colour
            )

            code_fenced_results = dict(map(
                lambda t: (t[0], f'```{highlight_lang}\n{t[1]}```') if t[1] else (t[0], '—'), result.items()
            ))
            code_fenced_results['status'] = result['status']

            for field, s in code_fenced_results.items():
                result_embed.add_field(name=field.replace('_', ' ').title(), value=s, inline=False)

            result_embed.set_footer(text=f'Code run at {datetime.now(tz=timezone.utc):%Y/%m/%d %H:%M:%S%z}')

            await inter.followup.send(embed=result_embed)


@client.tree.command(
    description='Run your code (up to 4000 characters) and view its output right here in Discord! '
                'Over 25 different languages supported each with several language versions.',
    guild=SYNC_GUILD
)
async def code(inter: discord.Interaction):
    await inter.response.send_message(
        content='Please select a language to run your code with.\n*Use the buttons to see more languages.* '
                '(Discord limits the dropdown to 25 items 🥲)',
        view=LanguageSelectMenuView(inter), ephemeral=False
    )


@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game('with /code'))

    await client.tree.sync(guild=SYNC_GUILD)

    console_log_with_time('Bot ready & running - hit me with code!')


# DEPLOY TODO: hardcode token
client.run(os.environ['DISCORD_CODE_TOKEN'])
