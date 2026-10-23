"""Gọi GraphQL API của Facebook qua JS trong trang đang mở.

``GraphQLMixin`` chứa phần transport dùng chung: lấy token live (fb_dtsg,
lsd, user id), dựng payload, gọi ``/api/graphql/`` và xử lý response
NDJSON. Phần phân trang/parse dữ liệu thuộc về từng nhóm chức năng.
"""

from __future__ import annotations

import base64
import json
import uuid

from services.comment_extractor import (
    feedback_global_id,
    reply_feedback_global_id,
)
from services.reaction_extractor import normalize_reaction_type

# Persisted query dùng cho từng loại dữ liệu.
GROUP_MEMBERS_DOC_ID = "27114388448203693"
GROUP_MEMBERS_FRIENDLY_NAME = "GroupsCometMembersPageNewMembersSectionRefetchQuery"
THINGS_IN_COMMON_DOC_ID = "27277860175202851"
THINGS_IN_COMMON_FRIENDLY_NAME = (
    "GroupsCometMembersWithThingsInCommonCardPaginationQuery"
)
SEARCH_POSTS_DOC_ID = "39411546341825607"
SEARCH_POSTS_FRIENDLY_NAME = "SearchCometResultsPaginatedResultsQuery"
COMMENTS_DOC_ID = "29265821953021786"
COMMENTS_FRIENDLY_NAME = "CommentsListComponentsPaginationQuery"
REPLIES_DOC_ID = "29170168959337360"
REPLIES_FRIENDLY_NAME = "Depth1CommentsListPaginationQuery"
REACTIONS_DOC_ID = "29771866012403077"
REACTIONS_FRIENDLY_NAME = "CometUFIReactionsDialogTabContentRefetchQuery"

# ID của từng loại reaction. ``None`` tương ứng tab "Tất cả".
REACTION_TYPE_IDS = {
    "LIKE": "1635855486666999",
    "LOVE": "1678524932434102",
    "CARE": "613557422527858",
    "HAHA": "115940658764963",
    "WOW": "478547315650144",
    "SAD": "908563459236466",
    "ANGRY": "444813342392137",
}

# Các Relay provider variable bắt buộc của 2 persisted query bình luận.
COMMENT_RELAY_PROVIDER_VARIABLES = {
    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
    "__relay_internal__pv__IsWorkUserrelayprovider": False,
}

# Filter "Bài đăng gần đây" của trang Search. Facebook nhận filter dưới dạng
# chuỗi JSON đã serialize, không phải object.
RECENT_POSTS_FILTER = json.dumps(
    {"name": "recent_posts", "args": ""}, separators=(",", ":")
)

# Cùng filter nhưng ở dạng tham số `filters` trên URL trang Search, để phần
# trích xuất DOM cũng thấy đúng danh sách bài mới nhất.
RECENT_POSTS_URL_FILTER = base64.urlsafe_b64encode(
    json.dumps(
        {"recent_posts:0": RECENT_POSTS_FILTER}, separators=(",", ":")
    ).encode("utf-8")
).decode("ascii")


def build_comments_variables(
    post_id: str,
    cursor: str = None,
    count: int = -1,
) -> dict:
    """Dựng variables cho trang bình luận đầu tiên/kế tiếp.

    Trang đầu tiên dùng ``cursor=None``. Facebook có thể trả trang gần nhất
    với ``commentsAfterCursor``; phần kiểm tra live nằm ở test/CLI.
    """
    variables = {
        "commentsAfterCount": int(count) if count is not None else None,
        "commentsAfterCursor": cursor,
        "commentsBeforeCount": None,
        "commentsBeforeCursor": None,
        "commentsIntentToken": None,
        "feedLocation": "POST_PERMALINK_DIALOG",
        "focusCommentID": None,
        "id": feedback_global_id(str(post_id)),
        "scale": 1,
        "targetDialect": None,
        "useDefaultActor": False,
    }
    variables.update(COMMENT_RELAY_PROVIDER_VARIABLES)
    return variables


def build_replies_variables(
    post_id: str,
    parent_comment_id: str,
    expansion_token: str,
    cursor: str = None,
) -> dict:
    """Dựng variables cho trang reply của một comment cha."""
    variables = {
        "clientKey": None,
        "expansionToken": expansion_token,
        "feedLocation": "POST_PERMALINK_DIALOG",
        "focusCommentID": None,
        "id": reply_feedback_global_id(
            str(post_id), str(parent_comment_id)
        ),
        "repliesAfterCount": None,
        "repliesAfterCursor": cursor,
        "repliesBeforeCount": None,
        "repliesBeforeCursor": None,
        "scale": 1,
        "useDefaultActor": False,
    }
    variables.update(COMMENT_RELAY_PROVIDER_VARIABLES)
    return variables


def resolve_reaction_id(
    reaction_type: str = None,
    reaction_id: str = None,
) -> str | None:
    """Đổi tên loại reaction (LIKE/LOVE...) thành ID Facebook."""
    if reaction_id:
        return str(reaction_id)

    key = normalize_reaction_type(reaction_type)
    if key in {"", "ALL", "TAT CA", "TẤT CẢ"}:
        return None
    if key in REACTION_TYPE_IDS:
        return REACTION_TYPE_IDS[key]
    if key.isdigit():
        return key
    raise ValueError(f"Loại reaction không hỗ trợ: {reaction_type}")


def build_reactions_variables(
    post_id: str,
    cursor: str = None,
    count: int = 10,
    reaction_type: str = None,
    reaction_id: str = None,
    name_query: str = None,
) -> dict:
    """Dựng variables cho tab người thả reaction của một bài viết.

    Trang đầu dùng ``cursor=None``; các trang sau dùng ``end_cursor`` từ
    response trước. ``reaction_type=None`` tương ứng tab "Tất cả".
    """
    target_id = feedback_global_id(str(post_id))
    return {
        "count": int(count) if count is not None else 10,
        "cursor": cursor,
        "feedbackTargetID": target_id,
        "nameQuery": str(name_query).strip() if name_query else None,
        "reactionID": resolve_reaction_id(reaction_type, reaction_id),
        "scale": 1,
        "id": target_id,
    }


class GraphQLMixin:
    """Transport GraphQL: nhận response thô, không parse thành domain object."""

    def fetch_group_members(
        self,
        group_id: str,
        cursor: str = None,
        count: int = 10,
        doc_id: str = GROUP_MEMBERS_DOC_ID,
        friendly_name: str = GROUP_MEMBERS_FRIENDLY_NAME,
    ) -> dict:
        """Thực thi GraphQL request với doc_id và friendly_name linh hoạt (An toàn 100% thread)."""
        js_script = """
            const done = arguments[arguments.length - 1];
            const groupId = arguments[0];
            const cursor = arguments[1];
            const count = arguments[2];
            const docId = arguments[3];
            const friendlyName = arguments[4];

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    done({ error: "JS_FETCH_TIMEOUT" });
                }, 10000);

                // 1. LẤY CÁC TOKEN BẢO MẬT (DTSG, USER_ID, LSD)
                let dtsgToken = "", userId = "", lsdToken = "";
                
                try { dtsgToken = (window.require && require('DTSGInitialData').token) || ""; } catch(e){}
                try { userId = (window.require && require('CurrentUserInitialData').USER_ID) || ""; } catch(e){}
                try { lsdToken = (window.require && require('LSD').token) || ""; } catch(e){}

                // Fallback qua Cookie nếu thiếu
                if (!dtsgToken) {
                    const m = document.cookie.match(/fb_dtsg=([^;]+)/);
                    if (m) dtsgToken = decodeURIComponent(m[1]);
                }
                if (!userId) {
                    const m = document.cookie.match(/c_user=([0-9]+)/);
                    if (m) userId = m[1];
                }

                if (!dtsgToken || !userId) {
                    clearTimeout(timeoutId);
                    return done({ error: "MISSING_AUTH_TOKENS" });
                }

                // 2. TÍNH JAZOEST
                let sum = 0;
                for (let i = 0; i < dtsgToken.length; i++) sum += dtsgToken.charCodeAt(i);
                const jazoest = '2' + sum;

                // 3. TỰ ĐỘNG LẤY TELEMETRY TỪ WINDOW (NẾU CÓ) ĐỂ TĂNG CONTENT-LENGTH LÊN 3000+ BYTES
                let rev = "", spinT = "";
                try { rev = (window.SiteData && window.SiteData.client_revision) || ""; } catch(e){}
                try { spinT = (window.Env && window.Env.start_time) || ""; } catch(e){}

                // 4. XÂY DỰNG PAYLOAD HOÀN CHỈNH
                const payloadMap = {
                    'av': userId,
                    '__user': userId,
                    'fb_dtsg': dtsgToken,
                    'jazoest': jazoest,
                    'lsd': lsdToken,
                    'fb_api_caller_class': 'RelayModern',
                    'fb_api_req_friendly_name': friendlyName,
                    'server_timestamps': 'true',
                    'doc_id': docId,
                    'variables': JSON.stringify({
                        'count': count,
                        'cursor': cursor ? cursor : null,
                        'groupID': groupId,
                        'recruitingGroupFilterNonCompliant': false,
                        'scale': 1,
                        'id': groupId
                    }),
                    '__a': '1',
                    '__comet_req': '15'
                };

                if (rev) payloadMap['__rev'] = rev;
                if (spinT) payloadMap['__spin_t'] = spinT;

                const payload = new URLSearchParams(payloadMap);

                // 5. GỬI FETCH CÓ CHỨA CÁC CUSTOM HEADERS X-
                fetch('https://www.facebook.com/api/graphql/', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Asbd-Id': '359341',
                        'X-Fb-Friendly-Name': friendlyName,
                        'X-Fb-Lsd': lsdToken
                    },
                    body: payload.toString(),
                    credentials: 'include',
                    signal: controller.signal
                })
                .then(async res => {
                    clearTimeout(timeoutId);
                    const text = await res.text();
                    const clean = text.replace(/^\\uFEFF/, '').trim();
                    try {
                        done(JSON.parse(clean));
                    } catch(jsonErr) {
                        // Một số response bị chia thành nhiều JSON object (NDJSON).
                        // Ghép riêng edges/page_info để parser vẫn dùng được.
                        try {
                            const lines = clean.split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);
                            if (lines.length > 1) {
                                const objects = lines.map(line => JSON.parse(line));
                                const merged = { data: { serpResponse: { results: { edges: [] } } } };
                                for (const obj of objects) {
                                    const results = obj && obj.data && obj.data.serpResponse && obj.data.serpResponse.results;
                                    if (results && Array.isArray(results.edges)) {
                                        merged.data.serpResponse.results.edges.push(...results.edges);
                                    }
                                    if (results && results.page_info) {
                                        merged.data.serpResponse.results.page_info = results.page_info;
                                    }
                                    if (obj && obj.extensions) {
                                        merged.extensions = obj.extensions;
                                    }
                                }
                                return done(merged);
                            }
                        } catch (streamErr) {}

                        done({
                            error: "INVALID_JSON_RESPONSE",
                            parse_error: jsonErr.toString(),
                            raw: clean.substring(0, 2000),
                            raw_length: clean.length,
                            content_type: res.headers.get('content-type') || ''
                        });
                    }
                })
                .catch(err => {
                    clearTimeout(timeoutId);
                    if (err.name === 'AbortError') return;
                    done({ error: err.toString() });
                });

            } catch(topErr) {
                done({ error: "CRITICAL_JS_ERROR: " + topErr.toString() });
            }
        """
        return self.driver.execute_async_script(
            js_script,
            str(group_id),
            cursor,
            count,
            str(doc_id),
            str(friendly_name),
        )

    def fetch_search_posts(
        self,
        keyword: str,
        cursor: str = None,
        count: int = 10,
        doc_id: str = SEARCH_POSTS_DOC_ID,
        friendly_name: str = SEARCH_POSTS_FRIENDLY_NAME,
        recent_posts: bool = False,
    ) -> dict:
        """Gọi GraphQL Search giống cách ``fetch_group_members`` lấy token live.

        Không hardcode fb_dtsg/lsd/telemetry. Cursor là chuỗi end_cursor lấy từ
        ``data.serpResponse.results.page_info`` của response trước đó.

        ``recent_posts=True`` thêm filter ``recent_posts`` vào ``args.filters``
        để Facebook trả về bài mới nhất thay vì kết quả mặc định.
        """
        variables = {
            "allow_streaming": False,
            "args": {
                "callsite": "COMET_GLOBAL_SEARCH",
                "config": {
                    "exact_match": False,
                    "high_confidence_config": None,
                    "intercept_config": None,
                    "sts_disambiguation": None,
                    "watch_config": None,
                },
                "context": {"bsid": str(uuid.uuid4()), "tsid": None},
                "experience": {
                    "client_defined_experiences": ["ADS_PARALLEL_FETCH"],
                    "encoded_server_defined_params": None,
                    "fbid": None,
                    "type": "GLOBAL_SEARCH",
                },
                "filters": [RECENT_POSTS_FILTER] if recent_posts else [],
                "text": str(keyword or ""),
            },
            "count": int(count),
            "cursor": cursor,
            "feedLocation": "SEARCH",
            "feedbackSource": 23,
            "fetch_filters": True,
            "focusCommentID": None,
            "locale": None,
            "privacySelectorRenderLocation": "COMET_STREAM",
            "referringStoryRenderLocation": None,
            "renderLocation": "search_results_page",
            "scale": 1,
            "stream_initial_count": 0,
            "useDefaultActor": False,
            # Các Relay provider variable bắt buộc của persisted query. Thiếu
            # chúng Facebook trả missing_required_variable_value.
            "__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider": True,
            "__relay_internal__pv__GHLShouldChangeSponsoredDataFieldNamerelayprovider": True,
            "__relay_internal__pv__CometFeedStory_enable_reactor_facepilerelayprovider": False,
            "__relay_internal__pv__CometFeedStory_enable_social_bubblesrelayprovider": False,
            "__relay_internal__pv__CometFeedStory_enable_post_permalink_white_space_clickrelayprovider": False,
            "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
            "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
            "__relay_internal__pv__IsWorkUserrelayprovider": False,
            "__relay_internal__pv__TestPilotShouldIncludeDemoAdUseCaserelayprovider": False,
            "__relay_internal__pv__FBReels_deprecate_short_form_video_context_gkrelayprovider": True,
            "__relay_internal__pv__CometUFI_dedicated_comment_routable_dialog_gkrelayprovider": True,
            "__relay_internal__pv__FBReels_enable_view_dubbed_audio_type_gkrelayprovider": True,
            "__relay_internal__pv__CometFeedShareMedia_shouldPrefetchShareImagerelayprovider": True,
            "__relay_internal__pv__CometImmersivePhotoCanUserDisable3DMotionrelayprovider": False,
            "__relay_internal__pv__WorkCometIsEmployeeGKProviderrelayprovider": False,
            "__relay_internal__pv__IsMergQAPollsrelayprovider": False,
            "__relay_internal__pv__FBReelsMediaFooter_comet_enable_reels_ads_gkrelayprovider": True,
            "__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider": False,
            "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
            "__relay_internal__pv__CometUFIShareActionMigrationrelayprovider": True,
            "__relay_internal__pv__CometUFISingleLineUFIrelayprovider": True,
            "__relay_internal__pv__relay_provider_comet_ufi_ssr_seo_deferrelayprovider": True,
            "__relay_internal__pv__FBReelsIFUTileContent_reelsIFUPlayOnHoverrelayprovider": True,
            "__relay_internal__pv__GroupsCometGYSJFeedItemHeightrelayprovider": 206,
            "__relay_internal__pv__StoriesShouldEnablePhotosensitiveContentWarningrelayprovider": False,
            "__relay_internal__pv__ShouldEnableBakedInTextStoriesrelayprovider": False,
            "__relay_internal__pv__StoriesShouldIncludeFbNotesrelayprovider": True,
        }

        js_script = """
            const done = arguments[arguments.length - 1];
            const variablesJson = arguments[0];
            const docId = arguments[1];
            const friendlyName = arguments[2];

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    done({ error: "JS_FETCH_TIMEOUT" });
                }, 15000);

                let dtsgToken = "", userId = "", lsdToken = "";
                try { dtsgToken = (window.require && require('DTSGInitialData').token) || ""; } catch(e){}
                try { userId = (window.require && require('CurrentUserInitialData').USER_ID) || ""; } catch(e){}
                try { lsdToken = (window.require && require('LSD').token) || ""; } catch(e){}

                if (!dtsgToken) {
                    const m = document.cookie.match(/fb_dtsg=([^;]+)/);
                    if (m) dtsgToken = decodeURIComponent(m[1]);
                }
                if (!userId) {
                    const m = document.cookie.match(/c_user=([0-9]+)/);
                    if (m) userId = m[1];
                }
                if (!dtsgToken || !userId) {
                    clearTimeout(timeoutId);
                    return done({ error: "MISSING_AUTH_TOKENS" });
                }

                let sum = 0;
                for (let i = 0; i < dtsgToken.length; i++) sum += dtsgToken.charCodeAt(i);
                const jazoest = '2' + sum;

                let rev = "", spinT = "";
                try { rev = (window.SiteData && window.SiteData.client_revision) || ""; } catch(e){}
                try { spinT = (window.Env && window.Env.start_time) || ""; } catch(e){}

                const payloadMap = {
                    'av': userId,
                    '__user': userId,
                    'fb_dtsg': dtsgToken,
                    'jazoest': jazoest,
                    'lsd': lsdToken,
                    'fb_api_caller_class': 'RelayModern',
                    'fb_api_req_friendly_name': friendlyName,
                    'server_timestamps': 'true',
                    'doc_id': docId,
                    'variables': variablesJson,
                    '__a': '1',
                    '__comet_req': '15'
                };
                if (rev) payloadMap['__rev'] = rev;
                if (spinT) payloadMap['__spin_t'] = spinT;

                const payload = new URLSearchParams(payloadMap);
                fetch('https://www.facebook.com/api/graphql/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Asbd-Id': '359341',
                        'X-Fb-Friendly-Name': friendlyName,
                        'X-Fb-Lsd': lsdToken
                    },
                    body: payload.toString(),
                    credentials: 'include',
                    signal: controller.signal
                })
                .then(async res => {
                    clearTimeout(timeoutId);
                    const text = await res.text();
                    const clean = text.replace(/^\\uFEFF/, '').trim();
                    try {
                        done(JSON.parse(clean));
                    } catch(jsonErr) {
                        // Một số response bị chia thành nhiều JSON object (NDJSON).
                        // Ghép riêng edges/page_info để parser vẫn dùng được.
                        try {
                            const lines = clean.split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);
                            if (lines.length > 1) {
                                const objects = lines.map(line => JSON.parse(line));
                                const merged = { data: { serpResponse: { results: { edges: [] } } } };
                                for (const obj of objects) {
                                    const results = obj && obj.data && obj.data.serpResponse && obj.data.serpResponse.results;
                                    if (results && Array.isArray(results.edges)) {
                                        merged.data.serpResponse.results.edges.push(...results.edges);
                                    }
                                    if (results && results.page_info) {
                                        merged.data.serpResponse.results.page_info = results.page_info;
                                    }
                                    if (obj && obj.extensions) {
                                        merged.extensions = obj.extensions;
                                    }
                                }
                                return done(merged);
                            }
                        } catch (streamErr) {}

                        done({
                            error: "INVALID_JSON_RESPONSE",
                            parse_error: jsonErr.toString(),
                            raw: clean.substring(0, 2000),
                            raw_length: clean.length,
                            content_type: res.headers.get('content-type') || ''
                        });
                    }
                })
                .catch(err => {
                    clearTimeout(timeoutId);
                    if (err.name === 'AbortError') return;
                    done({ error: err.toString() });
                });
            } catch(topErr) {
                done({ error: "CRITICAL_JS_ERROR: " + topErr.toString() });
            }
        """
        return self.driver.execute_async_script(
            js_script,
            json.dumps(variables, ensure_ascii=False),
            str(doc_id),
            str(friendly_name),
        )

    def _execute_graphql(
        self,
        variables: dict,
        doc_id: str,
        friendly_name: str,
        timeout_seconds: int = 20,
    ) -> dict:
        """Gửi một persisted query bất kỳ và trả JSON thô.

        Dùng chung token live giống ``fetch_search_posts``; không hardcode
        fb_dtsg/lsd. Response comments/replies của Facebook là một JSON object,
        nhưng vẫn có fallback đọc NDJSON để tránh lỗi khi Facebook stream.
        """
        js_script = """
            const done = arguments[arguments.length - 1];
            const variablesJson = arguments[0];
            const docId = arguments[1];
            const friendlyName = arguments[2];
            const timeoutMs = arguments[3];

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    done({ error: "JS_FETCH_TIMEOUT" });
                }, timeoutMs);

                let dtsgToken = "", userId = "", lsdToken = "";
                try { dtsgToken = (window.require && require('DTSGInitialData').token) || ""; } catch(e){}
                try { userId = (window.require && require('CurrentUserInitialData').USER_ID) || ""; } catch(e){}
                try { lsdToken = (window.require && require('LSD').token) || ""; } catch(e){}

                if (!dtsgToken) {
                    const m = document.cookie.match(/fb_dtsg=([^;]+)/);
                    if (m) dtsgToken = decodeURIComponent(m[1]);
                }
                if (!userId) {
                    const m = document.cookie.match(/c_user=([0-9]+)/);
                    if (m) userId = m[1];
                }
                if (!dtsgToken || !userId) {
                    clearTimeout(timeoutId);
                    return done({ error: "MISSING_AUTH_TOKENS" });
                }

                let sum = 0;
                for (let i = 0; i < dtsgToken.length; i++) sum += dtsgToken.charCodeAt(i);
                const jazoest = '2' + sum;

                let rev = "", spinT = "";
                try { rev = (window.SiteData && window.SiteData.client_revision) || ""; } catch(e){}
                try { spinT = (window.Env && window.Env.start_time) || ""; } catch(e){}

                const payloadMap = {
                    'av': userId,
                    '__user': userId,
                    'fb_dtsg': dtsgToken,
                    'jazoest': jazoest,
                    'lsd': lsdToken,
                    'fb_api_caller_class': 'RelayModern',
                    'fb_api_req_friendly_name': friendlyName,
                    'server_timestamps': 'true',
                    'doc_id': docId,
                    'variables': variablesJson,
                    '__a': '1',
                    '__comet_req': '15'
                };
                if (rev) payloadMap['__rev'] = rev;
                if (spinT) payloadMap['__spin_t'] = spinT;

                const payload = new URLSearchParams(payloadMap);
                fetch('https://www.facebook.com/api/graphql/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Asbd-Id': '359341',
                        'X-Fb-Friendly-Name': friendlyName,
                        'X-Fb-Lsd': lsdToken
                    },
                    body: payload.toString(),
                    credentials: 'include',
                    signal: controller.signal
                })
                .then(async res => {
                    clearTimeout(timeoutId);
                    const text = await res.text();
                    const clean = text.replace(/^\\uFEFF/, '').trim();
                    try {
                        done(JSON.parse(clean));
                    } catch(jsonErr) {
                        try {
                            const lines = clean.split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);
                            if (lines.length > 1) {
                                const objects = lines.map(line => JSON.parse(line));
                                const withData = objects.find(obj => obj && obj.data);
                                if (withData) {
                                    if (!withData.extensions) withData.extensions = {};
                                    withData.extensions.ndjson_objects = objects.length;
                                    return done(withData);
                                }
                            }
                        } catch (streamErr) {}

                        done({
                            error: "INVALID_JSON_RESPONSE",
                            parse_error: jsonErr.toString(),
                            raw: clean.substring(0, 2000),
                            raw_length: clean.length,
                            content_type: res.headers.get('content-type') || ''
                        });
                    }
                })
                .catch(err => {
                    clearTimeout(timeoutId);
                    if (err.name === 'AbortError') return;
                    done({ error: err.toString() });
                });
            } catch(topErr) {
                done({ error: "CRITICAL_JS_ERROR: " + topErr.toString() });
            }
        """
        return self.driver.execute_async_script(
            js_script,
            json.dumps(variables, ensure_ascii=False),
            str(doc_id),
            str(friendly_name),
            int(timeout_seconds * 1000),
        )

    def fetch_comments_page(
        self,
        post_id: str,
        cursor: str = None,
        count: int = -1,
        doc_id: str = COMMENTS_DOC_ID,
        friendly_name: str = COMMENTS_FRIENDLY_NAME,
    ) -> dict:
        """Lấy một trang bình luận top-level của bài viết/reel."""
        print(
            f"[GraphQL] Comments request: post_id={post_id}, "
            f"cursor={(str(cursor)[:24] + '...') if cursor and len(str(cursor)) > 24 else (cursor or 'first')}, "
            f"count={count}"
        )
        variables = build_comments_variables(post_id, cursor=cursor, count=count)
        response = self._execute_graphql(variables, doc_id, friendly_name)
        if isinstance(response, dict) and response.get("error"):
            print(f"[GraphQL] Comments response lỗi: {response.get('error')}")
        return response

    def fetch_replies_page(
        self,
        post_id: str,
        parent_comment_id: str,
        expansion_token: str,
        cursor: str = None,
        doc_id: str = REPLIES_DOC_ID,
        friendly_name: str = REPLIES_FRIENDLY_NAME,
    ) -> dict:
        """Lấy một trang reply của comment cha."""
        print(
            f"[GraphQL] Replies request: post_id={post_id}, "
            f"parent={parent_comment_id}, "
            f"cursor={(str(cursor)[:24] + '...') if cursor and len(str(cursor)) > 24 else (cursor or 'first')}"
        )
        variables = build_replies_variables(
            post_id,
            parent_comment_id,
            expansion_token,
            cursor=cursor,
        )
        response = self._execute_graphql(variables, doc_id, friendly_name)
        if isinstance(response, dict) and response.get("error"):
            print(f"[GraphQL] Replies response lỗi: {response.get('error')}")
        return response

    def fetch_reactions_page(
        self,
        post_id: str,
        cursor: str = None,
        count: int = 10,
        reaction_type: str = None,
        reaction_id: str = None,
        name_query: str = None,
        doc_id: str = REACTIONS_DOC_ID,
        friendly_name: str = REACTIONS_FRIENDLY_NAME,
    ) -> dict:
        """Lấy một trang người thả reaction/like của bài viết."""
        print(
            f"[GraphQL] Reactions request: post_id={post_id}, "
            f"cursor={(str(cursor)[:24] + '...') if cursor and len(str(cursor)) > 24 else (cursor or 'first')}, "
            f"count={count}, reaction={reaction_type or reaction_id or 'all'}"
        )
        variables = build_reactions_variables(
            post_id,
            cursor=cursor,
            count=count,
            reaction_type=reaction_type,
            reaction_id=reaction_id,
            name_query=name_query,
        )
        response = self._execute_graphql(variables, doc_id, friendly_name)
        if isinstance(response, dict) and response.get("error"):
            print(
                f"[GraphQL] Reactions response lỗi: {response.get('error')}"
            )
        return response
