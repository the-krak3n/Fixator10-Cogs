from contextlib import suppress
from io import BytesIO

import aiohttp
import discord
from redbot.core import commands
from redbot.core.config import Config
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils import chat_formatting as chat
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu

from .converters import ImageFinder
from .saucenao import SauceNAO
from .tracemoe import TraceMoe

try:
    from redbot import json  # support of Draper's branch
except ImportError:
    import json

_ = Translator("ReverseImageSearch", __file__)


async def send_preview(
    ctx: commands.Context,
    pages: list,
    controls: dict,
    message: discord.Message,
    page: int,
    timeout: float,
    emoji: str,
):
    # TODO: Use dpy menus/ui.view
    with suppress(discord.NotFound):
        await message.delete()
    doc = ctx.search_docs[page]
    async with ctx.typing():
        try:
            async with ctx.cog.session.get(doc.video, raise_for_status=True) as video_preview:
                video_preview = BytesIO(await video_preview.read())
                await ctx.send(
                    embed=pages[page],
                    file=discord.File(video_preview, filename=doc.filename),
                )
                video_preview.close()
        except aiohttp.ClientResponseError as e:
            await ctx.send(_("Unable to get video preview: {}").format(e.message))
        except discord.HTTPException as e:
            await ctx.send(_("Unable to send video preview: {}").format(e))


TRACEMOE_MENU_CONTROLS = {**DEFAULT_CONTROLS, "\N{FILM FRAMES}": send_preview}


def nsfwcheck():
    """
    Custom check that hide all commands used with it in the help formatter
    and block usage of them if used in a non-nsfw channel.
    """
    # original code is by preda:
    # https://github.com/PredaaA/predacogs/blob/9bd61dc494010829d4fecd9d550339aa58a412d3/nsfw/core.py#L206

    async def predicate(ctx: commands.Context):
        if (
            not ctx.guild
            or ctx.channel.is_nsfw()
            or ctx.invoked_with == "help"
            or ctx.invoked_subcommand
        ):
            return True
        if ctx.invoked_with not in [k for k in ctx.bot.all_commands]:
            # For this weird issue with last version of discord.py (1.2.3) with non-existing commands.
            # So this check is only for dev version of Red.
            # https://discordapp.com/channels/133049272517001216/133251234164375552/598149067268292648 for reference.
            # It probably need to check in d.py to see what is happening, looks like an issue somewhere.
            # It will probably removed in the future, it's a temporary check.
            return False
        try:
            await ctx.send(chat.error(_("You can't use this command in a non-NSFW channel!")))
        finally:
            return False

    return commands.check(predicate)


@cog_i18n(_)
class ReverseImageSearch(commands.Cog):
    """(Anime) Reverse Image Search"""

    __version__ = "2.1.12"

    # noinspection PyMissingConstructor
    def __init__(self, bot):
        self.bot = bot
        self.saucenao_limits = {
            "short": None,
            "long": None,
            "long_remaining": None,
            "short_remaining": None,
        }
        self.session = aiohttp.ClientSession(json_serialize=json.dumps)
        self.config = Config.get_conf(self, identifier=0x02E801D017C140A9A0C840BA01A25066)
        default_global = {"numres": 6}
        self.config.register_global(**default_global)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    async def red_delete_data_for_user(self, **kwargs):
        return

    @commands.group(invoke_without_command=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    @nsfwcheck()
    async def saucenao(self, ctx, image: ImageFinder = None):
        """[NSFW] Reverse search image via SauceNAO"""
        if image is None:
            try:
                image = await ImageFinder().search_for_images(ctx)
            except ValueError as e:
                await ctx.send(e)
                return
        image = image[0]
        try:
            search = await SauceNAO.from_image(ctx, image)
        except ValueError as e:
            await ctx.send(e)
            return
        if not search.results:
            await ctx.send(_("Nothing found"))
            return
        self.saucenao_limits["short"] = search.limits.short
        self.saucenao_limits["long"] = search.limits.long
        self.saucenao_limits["long_remaining"] = search.limits.remaining.long
        self.saucenao_limits["short_remaining"] = search.limits.remaining.short
        embeds = []
        page = 0
        for entry in search.results:
            page += 1
            try:
                url = entry.urls[0]
            except IndexError:
                url = discord.Embed.Empty
            # NOTE: Probably someone will come up with better embed design, but not me
            e = discord.Embed(
                title=entry.source or entry.title or entry.service,
                description="\n".join(
                    [
                        _("Similarity: {}%").format(entry.similarity),
                        "\n".join(n for n in [entry.eng_name, entry.jp_name] if n) or "",
                        entry.part and _("Part/Episode: {}").format(entry.part) or "",
                        entry.year and _("Year: {}").format(entry.year) or "",
                        entry.est_time and _("Est. Time: {}").format(entry.est_time) or "",
                    ]
                ),
                url=url,
                color=await ctx.embed_colour(),
                timestamp=entry.created_at or discord.Embed.Empty,
            )
            e.set_footer(
                text=_("Via SauceNAO • Page {}/{}").format(page, search.results_returned),
                icon_url="https://www.google.com/s2/favicons?domain=saucenao.com",
            )
            e.set_thumbnail(url=entry.image)
            embeds.append(e)
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            await ctx.send(chat.info(_("Nothing found")))

    @saucenao.command()
    @commands.is_owner()
    async def apikey(self, ctx):
        """Set API key for SauceNAO"""
        message = _(
            "To get SauceNAO API key:\n"
            "1. [Login](https://saucenao.com/user.php) to your SauceNAO account\n"
            "2. Go to [Search > api](https://saucenao.com/user.php?page=search-api) page\n"
            "3. Copy your *api key*\n"
            "4. Use `{}set api reverseimagesearch saucenao <your_api_key>`\n\n"
            "Note: These tokens are sensitive and should only be used in a private channel\n"
            "or in DM with the bot."
        ).format(ctx.clean_prefix)
        await ctx.maybe_send_embed(message)

    @saucenao.command(alises=["numres"])
    @commands.is_owner()
    async def maxres(self, ctx, results: int = 6):
        """Set API count of results count for SauceNAO

        6 by default"""
        await self.config.numres.set(results)
        await ctx.tick()

    @saucenao.command(name="stats")
    @commands.is_owner()
    async def saucenao_stats(self, ctx):
        """See how many requests are left"""
        if any(limit is not None for limit in self.saucenao_limits.values()):
            await ctx.send(
                _(
                    "Remaining requests:\nShort (30 seconds): {}/{}\nLong: (24 hours): {}/{}"
                ).format(
                    self.saucenao_limits["short_remaining"],
                    self.saucenao_limits["short"],
                    self.saucenao_limits["long_remaining"],
                    self.saucenao_limits["long"],
                )
            )
        else:
            await ctx.send(_("Command `{}` has not been used yet").format(self.saucenao))

    @commands.group(invoke_without_command=True, aliases=["WAIT", "ASSE"])
    @commands.cooldown(60, 60)
    async def tracemoe(self, ctx, image: ImageFinder = None):
        """Reverse search image via Anime Scene Search Engine

        If search performed not in NSFW channel, NSFW results will be not shown"""
        if image is None:
            try:
                image = await ImageFinder().search_for_images(ctx)
            except ValueError as e:
                await ctx.send(e)
                return
        image = image[0]
        try:
            search = await TraceMoe.from_image(ctx, image)
        except ValueError as e:
            await ctx.send(e)
            return
        embeds = []
        page = 0
        for doc in search.docs:
            page += 1
            if getattr(ctx.channel, "nsfw", True) and doc.is_adult:
                continue
            # NOTE: Probably someone will come up with better embed design, but not me
            e = discord.Embed(
                title=doc.title,
                description="\n".join(
                    s
                    for s in [
                        _("Similarity: {:.2f}%").format(doc.similarity * 100),
                        doc.title_romaji
                        and "🇯🇵 " + _("Romaji transcription: {}").format(doc.title_romaji),
                        doc.title_english
                        and "🇺🇸 " + _("English title: {}").format(doc.title_english),
                        _("Time: {}").format(doc.time_str),
                        _("Episode: {}").format(doc.episode),
                        doc.synonyms and _("Also known as: {}").format(", ".join(doc.synonyms)),
                    ]
                    if s
                ),
                url=doc.mal_id
                and f"https://myanimelist.net/anime/{doc.mal_id}"
                or f"https://anilist.co/anime/{doc.anilist_id}",
                color=await ctx.embed_color(),
            )
            e.set_thumbnail(url=doc.image)
            e.set_footer(
                text=_("Via Anime Scene Search Engine (trace.moe) • Page {}/{}").format(
                    page, len(search.docs)
                ),
                icon_url="https://trace.moe/favicon128.png",
            )
            embeds.append(e)
        if embeds:
            ctx.search_docs = search.docs
            await menu(ctx, embeds, TRACEMOE_MENU_CONTROLS)  # TODO: Use dpy menus/ui.view
        else:
            await ctx.send(chat.info(_("Nothing found")))

    @tracemoe.command(name="stats")
    @commands.is_owner()
    async def tracemoe_stats(self, ctx):
        """See how many requests are left and time until reset"""
        stats = await TraceMoe.me(ctx)
        await ctx.send(
            _("Priority: {}\n" "Concurrency: {}\n" "Quota: {}/{}").format(
                stats.priority, stats.concurrency, stats.quotaUsed, stats.quota
            )
        )
