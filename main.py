# invite: https://discord.com/api/oauth2/authorize?client_id=1014899163361722399&permissions=277025409024&scope=bot%20applications.commands

from __future__ import annotations

import os
import typing
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
import requests
from discord import app_commands


def console_log_with_time(msg: str, **kwargs):
    print(f'[code] {datetime.now(tz=timezone.utc):%Y/%m/%d %H:%M:%S%f%z} - {msg}', **kwargs)


class CodeRunnerClient(discord.Client):
    def __init__(self, guild_id: int):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.dev_guild_id = guild_id
        self.dev_sync_guild = discord.Object(id=self.dev_guild_id)

    async def setup_hook(self):
        # DEPLOY TODO: deploy = True
        deploy = False
        if deploy:
            self.tree.clear_commands(guild=self.dev_sync_guild)  # clear local commands
            await self.tree.sync(guild=self.dev_sync_guild)
            await self.tree.sync()  # global sync
            commands = await self.tree.fetch_commands()
        else:  # dev
            self.tree.copy_global_to(guild=self.dev_sync_guild)
            await self.tree.sync(guild=self.dev_sync_guild)
            commands = await self.tree.fetch_commands(guild=self.dev_sync_guild)

        console_log_with_time(f'Commands synced with {deploy=}.'
                              f'{" NB: Global commands may take an hour to appear." if deploy else ""}')
        for c in commands:
            console_log_with_time(f'Command ID {c.id} - "{c.name}" synced to Discord.')


client = CodeRunnerClient(851838718318215208)  # CompSoc Discord


def get_api_list() -> list:
    console_log_with_time('[api] GET list.json')
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


LANG_COUNT = len(get_languages())


class RunResponse(typing.TypedDict):
    status: str
    compiler_output: str
    compiler_error: str
    program_output: str
    program_error: str
    program_message: str


def run_code(raw_code: str, compiler: str, timelimit: int = 10) -> typing.Tuple[requests.Response, RunResponse]:
    # todo: compiler options? (mainly for C stuff)
    post_json = {
        'code': raw_code,
        'options': '',
        'compiler': compiler,
        'compiler-option-raw': ''
    }
    console_log_with_time(f'[api] POST compile.json with compiler: {compiler}')

    post = requests.post(
        'https://wandbox.org/api/compile.json', timeout=timelimit,
        json=post_json, headers={'Content-type': 'application/json'}
    )
    if post.elapsed >= timedelta(seconds=timelimit):
        console_log_with_time(f'Code-running POST request timed out after {timelimit}s')
        return post, {
            'status': 'timeout',
            'compiler_output': '',
            'compiler_error': '',
            'program_output': f'Your code took longer than {timelimit} seconds to run and was timed out.',
            'program_error': '',
            'program_message': ''
        }
    else:
        console_log_with_time(f'[api] POST returned status code {post.status_code}')
        return post, post.json()


async def different_user_error(inter: discord.Interaction):
    console_log_with_time(f"User {inter.user.id} tried to continue an interaction they didn't start.")

    await inter.response.send_message(
        content="You didn't initiate this interaction. Please use `/code` yourself to run your code.",
        ephemeral=True
    )


class MultiPageSelectView(discord.ui.View):
    # noinspection PyPep8Naming
    def __init__(self, inter: discord.Interaction, SelectClass: typing.Type[LanguageSelect | VersionSelect],
                 code_src: str, num_options: int = LANG_COUNT, selection: str = ''):
        super().__init__()
        self.origin_inter = inter
        self.code_src = code_src

        self.language_dict = get_languages()
        sorted_langs = sorted(self.language_dict.keys())

        if SelectClass == LanguageSelect:
            num_options = len(self.language_dict)  # override in case of update

        self.pages_req = num_options // 25 + 1  # Discord limits Select menus to 25 items
        self.current_page = 0

        self.select_objects = []
        for page_num in range(self.pages_req):
            self.select_objects.append(
                SelectClass(inter, self.language_dict, page_num, code_src,  # <- pos defaults for both SelectClasses
                            sorted_options=sorted_langs[page_num * 25:(page_num + 1) * 25], language=selection)
                # non-default arguments^ , sorted_options for LanguageSelect and selected_language for VersionSelect
            )

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

        self.add_item(self.select_objects[self.current_page])

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user != self.origin_inter.user:
            await different_user_error(inter)
            return False
        return True

    async def btn_back_callback(self, inter: discord.Interaction):
        await self.change_page(inter, -1)

    async def btn_next_callback(self, inter: discord.Interaction):
        await self.change_page(inter, 1)

    async def change_page(self, inter: discord.Interaction, change: int):
        self.remove_item(self.select_objects[self.current_page])
        self.current_page += change
        self.add_item(self.select_objects[self.current_page])

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

        console_log_with_time(f'User {inter.user.id} changed to pg.{self.current_page+1} for {self.__class__}')


class LanguageSelect(discord.ui.Select):
    def __init__(self, inter: discord.Interaction, language_dict: dict, page_num: int, code_src: str,
                 sorted_options: list, **kwargs):  # kwargs req. to accept argument potentially meant for other Select
        self.origin_inter = inter
        self.language_dict = language_dict
        self.code_src = code_src

        super().__init__(
            placeholder=f'[{page_num + 1}] Select a programming language',
            min_values=1, max_values=1, row=0
        )

        for lang in sorted_options:
            self.add_option(label=lang)

    async def callback(self, inter: discord.Interaction):
        selected_lang = self.values[0]
        version_select_view = MultiPageSelectView(self.origin_inter, VersionSelect, self.code_src,
                                                  len(self.language_dict[selected_lang]), selected_lang)
        await self.origin_inter.edit_original_response(
            content='Select the language version.',
            view=version_select_view
        )
        await inter.response.defer()

        console_log_with_time(f'User {inter.user.id} selected language: {selected_lang}')


class VersionSelect(discord.ui.Select):
    def __init__(self, inter: discord.Interaction, language_dict: dict, page_num: int, code_src: str,
                 language: str, **kwargs):
        self.origin_inter = inter
        self.selected_language = language
        self.code_src = code_src

        super().__init__(
            placeholder=f'[{page_num + 1}] Select a language version',
            min_values=1, max_values=1, row=0
        )

        for o in language_dict[self.selected_language]:
            self.add_option(label=o['name'], description=o['version'])

    async def callback(self, inter: discord.Interaction):
        selected_version = self.values[0]
        if self.code_src:
            await send_code(inter, self.selected_language, selected_version, self.origin_inter, self.code_src)
        else:
            await inter.response.send_modal(CodeEntry(self.selected_language, selected_version, self.origin_inter))

        console_log_with_time(f'User {inter.user.id} selected version: {selected_version}')


async def send_code(inter: discord.Interaction, language: str, version: str,
                    inter_to_edit: discord.Interaction, code_str: str):

    await inter.response.defer(thinking=True)

    highlight_lang = language.split(" ")[0].lower()

    console_log_with_time('Writing code to file')
    root = Path('./code/temp')
    root.mkdir(parents=True, exist_ok=True)
    temp_file = root / Path(f'{inter.user.id}.txt')
    with temp_file.open('w', encoding='utf-8') as fobj:
        fobj.write(code_str)

    response_str = f'{language} | {version}\nCode:\n```{highlight_lang}\n{code_str}```'[:2000]
    # noinspection PyTypeChecker
    attachments = [discord.File(temp_file.open('rb'), filename='full_code.txt')]

    console_log_with_time('Updating relevant interaction...')
    await inter_to_edit.edit_original_response(content=response_str, attachments=attachments, view=None)

    del attachments
    temp_file.unlink(missing_ok=True)

    error = ''
    result: RunResponse = dict()
    try:
        resp, result = run_code(code_str, version)
    except Exception as e:
        error = str(e)
    else:
        if not resp.ok:
            error = f'The POST request received a status of {resp.status_code}.'

    if error:
        console_log_with_time(f'Code run request failed: {error}')
        await inter.followup.send(
            content='The **request** to run your code failed (i.e. **not** the code itself).\n'
                    f'The following exception was raised by the program:\n```{error}```')
        return

    if 'status' not in result and 'signal' in result:
        result['status'] = result['signal']
        del result['signal']

    if result['status'] == 'Killed':
        result_colour = discord.Colour.gold()
    elif int(result['status']) == 0:
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
        result_embed.add_field(name=field.replace('_', ' ').title()[:256], value=s[:1024], inline=False)

    result_embed.set_footer(text=f'Code run at {datetime.now(tz=timezone.utc):%Y/%m/%d %H:%M:%S%z}')

    await inter.followup.send(embed=result_embed)

    console_log_with_time(f'Code run result sent in response to user {inter.user.id}')


class CodeEntry(discord.ui.Modal, title='Enter your Code'):
    code_entry = discord.ui.TextInput(label='Code', style=discord.TextStyle.paragraph)

    def __init__(self, language: str, version: str, origin_inter_to_edit: discord.Interaction):
        super().__init__()
        self.language = language
        self.version = version
        self.origin_inter_to_edit = origin_inter_to_edit

    async def on_submit(self, inter: discord.Interaction):
        console_log_with_time(f'User {inter.user.id} submitted a code modal')
        await send_code(inter, self.language, self.version, self.origin_inter_to_edit, str(self.code_entry))


@client.tree.command(
    description=f'Run your code in Discord with {LANG_COUNT} languages available! '
                'Just run the command to get started.'[:100]
)
@discord.app_commands.describe(
    file='UTF-8 encoded text file to read code from (e.g. .py, .js)',
    pastebin='https://pastebin.com/ link to read code from (e.g. https://pastebin.com/N3yL4Ugk)'
)
async def code(inter: discord.Interaction, file: typing.Optional[discord.Attachment], pastebin: typing.Optional[str]):

    console_log_with_time(f'/code command run by user {inter.user.id} in guild {inter.guild_id}. '
                          f'Using: {"file option" if file else ""} {"pastebin" if pastebin else ""}')

    code_src = None

    await inter.response.defer(thinking=True)

    if file and pastebin:
        await inter.followup.send(
            content='`file` and `pastebin` are mutually exclusive options. Please use just one.', ephemeral=True
        )
        return

    elif file:
        console_log_with_time('Reading and decoding attachment file.')
        code_bytes = await file.read()
        try:
            code_src = code_bytes.decode('utf-8')
        except UnicodeError:
            raise UnicodeError('There was an error decoding the file. '
                               'Make sure the file contains only utf-8 encoded text.')

    elif pastebin:
        console_log_with_time('Reading and decoding pastebin url.')
        url = pastebin
        raw_url_start = 'https://pastebin.com/raw/'
        if not pastebin.startswith(raw_url_start):
            url = raw_url_start + pastebin.split('/')[-1]

        error = f"Pastebin url ({url}) couldn't be resolved."
        resp = requests.Response
        resp.status_code = 0
        try:
            console_log_with_time(f'Getting {url}...')
            resp = requests.get(url)
        except Exception as e:
            error += f'\n{e}'

        if resp.ok:
            error = ''

        if error:
            raise ValueError(error)
        else:
            code_src = resp.text

    await inter.followup.send(
        content='Please select a language to run your code with.\n*Use the buttons to see more languages. '
                '(Discord limits the dropdown to 25 items 🥲)*',
        view=MultiPageSelectView(inter, LanguageSelect, code_src), ephemeral=False
    )


@code.error
async def code_error(inter: discord.Interaction, err: discord.app_commands.AppCommandError):
    console_log_with_time(f'Error with `/code` command: {err!s}')
    await inter.followup.send(
        content=str(err),
        ephemeral=False
    )


@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game('with /code'))

    console_log_with_time('Bot ready & running - hit me with code!')


# DEPLOY TODO: hardcode token
client.run(os.environ['DISCORD_CODE_TOKEN'])
